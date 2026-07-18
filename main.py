#!/usr/bin/env python3
"""
SP Migration Companion — FastAPI Backend
Exposes two endpoints:
  POST /analyze  — parse SQL file(s), return tables/columns/schemas/procedures
  POST /ai-insights — call HuggingFace Inference API for migration risk narrative
"""

import re
import os
import json
import requests
from pathlib import Path
from collections import defaultdict
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from limits import (
    active_tier, check_upload_limits, check_result_limits, TierLimitExceeded,
)


# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(
    title="SP Migration Companion API",
    description="Stored Procedure static analyzer for BSA migration planning",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://sql-sp-companion.vercel.app",
        "http://localhost:8000",
        "null",  # file:// origin, for people who just open index.html
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── HuggingFace config ────────────────────────────────────────────────────────
__version__ = "1.0.0"

# HF retired the legacy api-inference.huggingface.co text-generation endpoint in
# favor of an OpenAI-compatible chat-completions router. Mistral-7B-Instruct-v0.2
# is still served (single provider: featherless-ai), just through the new router.
HF_API_URL = "https://router.huggingface.co/v1/chat/completions"
HF_MODEL   = "mistralai/Mistral-7B-Instruct-v0.2"
HF_TOKEN   = os.getenv("HF_TOKEN", "")   # set via Render env var


# ═══════════════════════════════════════════════════════════════════════
# SQL PARSER  (same deterministic engine as the Python CLI)
# ═══════════════════════════════════════════════════════════════════════

SKIP_WORDS = {
    'SELECT','WHERE','SET','ON','AND','OR','NOT','IN','AS','WITH','BY','HAVING',
    'UNION','ALL','DISTINCT','TOP','NULL','BEGIN','END','IF','ELSE','THEN','CASE',
    'WHEN','RETURN','DECLARE','PRINT','GO','USE','OUTPUT','DEFAULT','VALUES',
    'EXISTS','COALESCE','ISNULL','CAST','CONVERT','GETDATE','SYSDATETIME','NEWID',
    'NOLOCK','READPAST','UPDLOCK','ROWLOCK','TABLOCK','INTO','FROM','EXEC',
    'EXECUTE','PROCEDURE','PROC','FUNCTION','TRIGGER','VIEW','TABLE','INDEX',
    'DATABASE','SCHEMA','SCOPE_IDENTITY','OBJECT_ID','ISNUMERIC','ISDATE','LEN',
    'LTRIM','RTRIM','UPPER','LOWER','SUBSTRING','CHARINDEX','REPLACE','STUFF',
    'DATEDIFF','DATEADD','YEAR','MONTH','DAY','COUNT','SUM','AVG','MIN','MAX',
    'ROW_NUMBER','RANK','DENSE_RANK','NTILE','LAG','LEAD','OVER','PARTITION',
    'INSERTED','DELETED','IDENTITY','CONSTRAINT','PRIMARY','FOREIGN','KEY',
    'NVARCHAR','VARCHAR','INT','BIGINT','DATETIME','DATE','BIT','DECIMAL','FLOAT',
    'CHAR','TEXT','UNIQUEIDENTIFIER','MONEY','SMALLINT','TINYINT','IMAGE',
    'OBJECT_NAME','DB_NAME','USER_NAME','SUSER_NAME','HOST_NAME','SYSTEM_USER',
    'QUOTENAME','BETWEEN','LIKE','IS','MATCHED','TARGET','SOURCE','USING',
    'ORDER','GROUP','INNER','LEFT','RIGHT','FULL','CROSS','OUTER','JOIN',
    'INSERT','UPDATE','DELETE','MERGE','TRUNCATE','CREATE','DROP','ALTER',
    'OFFSET','FETCH','NEXT','ROWS','ONLY',
}

TABLE_OP_PATTERNS = [
    (r'\bFROM\s+((?:[\w]+\.)*[\w]+)',               'SELECT'),
    (r'\bINNER\s+JOIN\s+((?:[\w]+\.)*[\w]+)',       'SELECT'),
    (r'\bLEFT\s+(?:OUTER\s+)?JOIN\s+((?:[\w]+\.)*[\w]+)',  'SELECT'),
    (r'\bRIGHT\s+(?:OUTER\s+)?JOIN\s+((?:[\w]+\.)*[\w]+)', 'SELECT'),
    (r'\bFULL\s+(?:OUTER\s+)?JOIN\s+((?:[\w]+\.)*[\w]+)',  'SELECT'),
    (r'\bCROSS\s+JOIN\s+((?:[\w]+\.)*[\w]+)',       'SELECT'),
    (r'\bJOIN\s+((?:[\w]+\.)*[\w]+)',               'SELECT'),
    (r'\bINSERT\s+INTO\s+((?:[\w]+\.)*[\w]+)',      'INSERT'),
    (r'\bUPDATE\s+((?:[\w]+\.)*[\w]+)\s+SET\b',    'UPDATE'),
    (r'\bDELETE\s+FROM\s+((?:[\w]+\.)*[\w]+)',      'DELETE'),
    (r'\bMERGE\s+(?:INTO\s+)?((?:[\w]+\.)*[\w]+)', 'MERGE'),
    (r'\bTRUNCATE\s+TABLE\s+((?:[\w]+\.)*[\w]+)',   'TRUNCATE'),
    (r'\bUSING\s+((?:[\w]+\.)*[\w]+)',              'SELECT'),
]

STMT_SPLIT = re.compile(
    r'(?=\b(?:SELECT|INSERT|UPDATE|DELETE|MERGE|TRUNCATE)\b)',
    re.IGNORECASE
)


def read_bytes_safe(raw: bytes) -> str:
    """Decode bytes trying common SQL file encodings."""
    if raw.startswith(b'\xef\xbb\xbf'):
        raw = raw[3:]
    for enc in ['utf-8', 'windows-1252', 'cp1252', 'latin-1']:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode('latin-1', errors='replace')


def mask_string_literals(sql: str) -> str:
    """
    Replace the CONTENTS of single-quoted string literals with a placeholder.

    Why: without this, `WHERE Notes = 'migrated FROM dbo.Phantom'` makes the
    FROM-pattern match inside the literal and invent a table that does not
    exist. That violates the "never invent" contract (see tests/test_contracts).

    It also makes the dynamic-SQL boundary honest: we flag EXEC/sp_executesql as
    unanalyzable, so we must not simultaneously half-report tables scraped out
    of the dynamic SQL string.

    Quote length is preserved so column offsets stay roughly stable. Escaped
    quotes ('') are handled by the alternation.
    """
    def blank(m):
        return "'" + ("\u0000" * (len(m.group(0)) - 2)) + "'"
    return re.sub(r"'(?:[^']|'')*'", blank, sql)


def clean_sql(sql: str) -> str:
    sql = re.sub(r'/\*.*?\*/', ' ', sql, flags=re.DOTALL)   # block comments
    sql = re.sub(r'--[^\n]*', ' ', sql)                      # line comments
    sql = mask_string_literals(sql)                          # literal contents
    sql = re.sub(r'\s+', ' ', sql)
    return sql.strip()


def normalize_bracketed(sql: str):
    """Replace [Multi Word] → MULTI_WORD and return mapping."""
    mapping = {}
    def replacer(m):
        inner  = m.group(1).strip()
        normed = re.sub(r'\s+', '_', inner).upper()
        mapping[normed] = inner
        return normed
    return re.sub(r'\[([^\]]+)\]', replacer, sql), mapping


def strip_quotes(n: str) -> str:
    return re.sub(r'[\[\]"`]', '', str(n)).strip()


def parse_table_ref(raw: str):
    raw   = strip_quotes(raw).strip()
    parts = [p for p in raw.split('.') if p]
    if len(parts) >= 2:
        schema = parts[-2].upper()
        base   = parts[-1].upper()
        return schema, base, f"{schema}.{base}"
    base = parts[0].upper() if parts else raw.upper()
    return '', base, base


def detect_dialect(sql: str) -> str:
    s = sql.upper()
    if re.search(r'DECLARE\s+@', s):           return 'T-SQL (SQL Server)'
    if re.search(r'LANGUAGE\s+PLPGSQL', s):    return 'PostgreSQL'
    if re.search(r'CREATE\s+OR\s+REPLACE', s): return 'Oracle/PostgreSQL'
    if re.search(r'`\w+`', sql):               return 'MySQL'
    return 'Auto-detected'


def split_procedures(sql: str):
    pat = re.compile(
        r'(CREATE\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|PROC|FUNCTION)\s+([\w\.\[\]"` ]+))',
        re.IGNORECASE
    )
    matches = list(pat.finditer(sql))
    if not matches:
        return [('UnnamedProcedure', sql)]
    procs = []
    for i, m in enumerate(matches):
        start = m.start()
        end   = matches[i+1].start() if i+1 < len(matches) else len(sql)
        name  = strip_quotes(m.group(2)).strip()
        procs.append((name, sql[start:end]))
    return procs


def extract_cte_info(norm: str):
    cte_names = set()
    cte_src   = {}
    cte_rx = re.compile(
        r'(?:,|\bWITH\b)\s*([\w]+)\s+AS\s*\((.*?)(?=\)\s*(?:,|\bSELECT\b|\bINSERT\b|\bUPDATE\b|\bDELETE\b|\bMERGE\b))',
        re.IGNORECASE | re.DOTALL
    )
    for m in cte_rx.finditer(norm):
        cname = m.group(1).upper()
        body  = m.group(2)
        cte_names.add(cname)
        fm = re.search(r'\bFROM\s+((?:[\w]+\.)*[\w]+)', body, re.IGNORECASE)
        if fm:
            _, base, full = parse_table_ref(fm.group(1))
            if base not in SKIP_WORDS and not base.startswith('#'):
                cte_src[cname] = full
    for m in re.finditer(r'\bWITH\b\s+([\w]+)\s+AS\s*\(', norm, re.IGNORECASE):
        cte_names.add(m.group(1).upper())
    return cte_names, cte_src


def resolve_cte(name, cte_src, cte_names, depth=0):
    if depth > 8: return None
    src = cte_src.get(name)
    if not src: return None
    if src in cte_names: return resolve_cte(src, cte_src, cte_names, depth+1)
    return src


def build_alias_map(stmt, cte_names):
    alias_map = {}
    pat = re.compile(
        r'(?:FROM|JOIN|UPDATE|MERGE\s+(?:INTO\s+)?)\s+'
        r'((?:[\w]+\.)*[\w]+)\s+(?:AS\s+)?([A-Za-z_]\w*)'
        r'(?=\s|\(|$|ON\b|SET\b|USING\b|WHERE\b|WITH\b)',
        re.IGNORECASE
    )
    for m in pat.finditer(stmt):
        traw  = strip_quotes(m.group(1))
        alias = m.group(2).upper()
        if alias in SKIP_WORDS or traw.startswith('#') or traw.startswith('@'):
            continue
        _, base, full = parse_table_ref(traw)
        if alias != base:
            alias_map[alias] = full
    # CTE direct alias
    cte_al = re.compile(
        r'(?:FROM|JOIN)\s+([\w]+)\s+(?:AS\s+)?([A-Za-z_]\w*)(?=\s|\(|$|ON\b|WHERE\b)',
        re.IGNORECASE
    )
    for m in cte_al.finditer(stmt):
        src   = m.group(1).upper()
        alias = m.group(2).upper()
        if src in cte_names and alias not in SKIP_WORDS:
            alias_map[alias] = src
    return alias_map


def parse_sp(sql: str):
    """Main extraction function. Returns dict with tables, columns, schemas."""
    clean      = clean_sql(sql)
    norm, bmap = normalize_bracketed(clean)
    cte_names, cte_src = extract_cte_info(norm)

    physical  = {}
    is_dynamic = bool(re.search(r'EXEC\s*\(|EXECUTE\s*\(|sp_executesql', clean, re.IGNORECASE))

    def register(full, schema, base, op):
        if full not in physical:
            physical[full] = {'schema': schema, 'base': base,
                               'ops': set(), 'aliases': set(), 'columns': set()}
        physical[full]['ops'].add(op)

    statements = [s.strip() for s in STMT_SPLIT.split(norm) if s.strip()]

    for stmt in statements:
        alias_map = build_alias_map(stmt, cte_names)

        # Resolve aliases through CTE chain
        resolved = {}
        for alias, target in alias_map.items():
            if target.upper() in cte_names:
                phys = resolve_cte(target.upper(), cte_src, cte_names)
                resolved[alias] = phys or target
            else:
                resolved[alias] = target
        for cname in cte_names:
            phys = resolve_cte(cname, cte_src, cte_names)
            if phys:
                resolved[cname] = phys

        stmt_tables = []
        for pat, op in TABLE_OP_PATTERNS:
            for m in re.finditer(pat, stmt, re.IGNORECASE):
                raw = m.group(1).strip()
                schema, base, full = parse_table_ref(raw)
                if (base in SKIP_WORDS or base in cte_names or full in cte_names
                        or base.startswith('#') or base.startswith('@') or len(base) < 2):
                    continue
                register(full, schema, base, op)
                if full not in stmt_tables:
                    stmt_tables.append(full)
                for a, t in alias_map.items():
                    if t == full and full in physical:
                        physical[full]['aliases'].add(a)

        # Qualified columns
        for cm in re.finditer(r'\b([\w]+)\.([\w]+)\b', stmt):
            prefix = cm.group(1).upper()
            col    = cm.group(2).upper()
            if col in SKIP_WORDS or col.startswith('@'):
                continue
            if not re.match(r'^[A-Z_][A-Z0-9_]*$', col):
                continue
            target = resolved.get(prefix)
            if not target:
                for k in physical:
                    if k == prefix or k.endswith('.' + prefix):
                        target = k; break
            if not target and prefix in cte_names:
                target = resolve_cte(prefix, cte_src, cte_names)
            if target and target in physical:
                physical[target]['columns'].add(col)

        # Unqualified SELECT — single table only
        for bm in re.finditer(r'\bSELECT\b(.*?)\bFROM\b', stmt, re.IGNORECASE | re.DOTALL):
            block = re.sub(r'\(.*?\)', '', bm.group(1), flags=re.DOTALL)
            block = re.sub(r"\bAS\s+(?:'[^']*'|\"[^\"]*\"|[\w_]+)", '', block, flags=re.IGNORECASE)
            for token in re.split(r'[,\s]+', block):
                token = token.split('.')[-1].upper().strip()
                if not token or token == '*' or token in SKIP_WORDS:
                    continue
                if not re.match(r'^[A-Z_][A-Z0-9_]*$', token):
                    continue
                if len(stmt_tables) == 1 and stmt_tables[0] in physical:
                    physical[stmt_tables[0]]['columns'].add(token)

    # Restore bracketed display names + deduplicate
    for key in list(physical.keys()):
        info = physical[key]
        restored = {bmap.get(c, c) for c in info['columns']}
        display_normed = {re.sub(r'\s+','',c).upper() for c in restored
                          if c in bmap.values() or ' ' in c}
        final = set()
        for col in restored:
            cn = re.sub(r'\s+', '', col).upper()
            if ' ' not in col and cn in display_normed:
                continue
            final.add(col)
        info['columns'] = final
        info['schema']  = bmap.get(info['schema'], info['schema'])
        info['base']    = bmap.get(info['base'],   info['base'])

    return physical, is_dynamic


# ═══════════════════════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@app.get("/")
def root():
    return {"service": "SP Migration Companion API", "version": __version__,
            "docs": "/docs", "status": "healthy"}


@app.get("/health")
def health():
    tier = active_tier()
    return {
        "status": "ok",
        "version": __version__,
        "hf_configured": bool(HF_TOKEN),
        "tier": tier.name,
        "limits": tier.as_dict(),
    }


@app.post("/analyze")
async def analyze(files: list[UploadFile] = File(...)):
    """
    Analyze one or more SQL files.
    Returns structured extraction: procedures, tables, columns, schema_map.
    Subject to the active tier's limits (see /health for current limits).
    """
    tier = active_tier()

    # Read all payloads up front so we can enforce size limits before parsing.
    payloads = []
    for upload in files:
        payloads.append((upload.filename, await upload.read()))

    try:
        check_upload_limits(tier, [len(raw) for _, raw in payloads])
    except TierLimitExceeded as e:
        raise HTTPException(status_code=413, detail={
            "error": "tier_limit_exceeded",
            "message": e.message,
            "limit": e.limit_name,
            "limit_value": e.limit_value,
            "actual": e.actual,
            "tier": tier.name,
        })

    all_procedures = []
    all_tables     = []
    all_columns    = []
    schema_map     = {}

    for filename, raw in payloads:
        sql     = read_bytes_safe(raw)
        dialect = detect_dialect(sql)
        procs   = split_procedures(sql)

        for pname, body in procs:
            physical, is_dynamic = parse_sp(body)
            phys_only = {k: v for k in physical
                         if k != '__UNRESOLVED__'
                         for v in [physical[k]]}

            proc_entry = {
                "name":       pname,
                "file":       filename,
                "dialect":    dialect,
                "is_dynamic": is_dynamic,
                "table_count": len(phys_only),
                "col_count":   sum(len(v['columns']) for v in phys_only.values()),
            }
            all_procedures.append(proc_entry)

            for full_key, info in sorted(phys_only.items()):
                schema  = info['schema'] or '(none)'
                base    = info['base']
                ops     = ', '.join(sorted(info['ops']))
                aliases = ', '.join(sorted(info['aliases'])) or '—'
                cols    = sorted(info['columns'])

                all_tables.append({
                    "proc":    pname,
                    "file":    filename,
                    "schema":  schema,
                    "table":   base,
                    "ops":     ops,
                    "aliases": aliases,
                })

                if not cols:
                    all_columns.append({
                        "proc":   pname,
                        "file":   filename,
                        "schema": schema,
                        "table":  base,
                        "col":    "(no columns resolved)",
                        "ops":    ops,
                    })
                else:
                    for col in cols:
                        all_columns.append({
                            "proc":   pname,
                            "file":   filename,
                            "schema": schema,
                            "table":  base,
                            "col":    col,
                            "ops":    ops,
                        })

                # Build schema map
                if schema not in schema_map:
                    schema_map[schema] = {}
                if base not in schema_map[schema]:
                    schema_map[schema][base] = {
                        "ops": ops,
                        "cols": [],
                        "procs": []
                    }
                for c in cols:
                    if c not in schema_map[schema][base]['cols']:
                        schema_map[schema][base]['cols'].append(c)
                if pname not in schema_map[schema][base]['procs']:
                    schema_map[schema][base]['procs'].append(pname)

    distinct_tables = len({f"{t['schema']}.{t['table']}" for t in all_tables})
    try:
        check_result_limits(tier, distinct_tables)
    except TierLimitExceeded as e:
        raise HTTPException(status_code=413, detail={
            "error": "tier_limit_exceeded",
            "message": e.message,
            "limit": e.limit_name,
            "limit_value": e.limit_value,
            "actual": e.actual,
            "tier": tier.name,
        })

    from datetime import datetime, timezone
    return {
        "status":     "success",
        "meta": {
            "tool":         "sql-sp-companion",
            "version":      __version__,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "files":        [fn for fn, _ in payloads],
            "tier":         tier.name,
        },
        "procedures": all_procedures,
        "tables":     all_tables,
        "columns":    all_columns,
        "schema_map": schema_map,
        "stats": {
            "total_procedures": len(all_procedures),
            "total_tables":     len(set(f"{t['schema']}.{t['table']}" for t in all_tables)),
            "total_schemas":    len(schema_map),
            "total_columns":    len([c for c in all_columns if c['col'] != '(no columns resolved)']),
            "dynamic_sql_count": sum(1 for p in all_procedures if p['is_dynamic']),
        }
    }


class AIInsightRequest(BaseModel):
    procedures: list
    tables:     list
    columns:    list
    schema_map: dict
    focus_proc: Optional[str] = None   # if set, focus insights on this procedure


@app.post("/ai-insights")
async def ai_insights(req: AIInsightRequest):
    """
    Send extracted SP metadata to HuggingFace Mistral-7B
    and return a migration risk narrative.
    """
    if not HF_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="HuggingFace token not configured. Set HF_TOKEN environment variable."
        )

    # Build a compact but rich summary to send to the model
    schemas     = list(req.schema_map.keys())
    total_tables= len(set(f"{t['schema']}.{t['table']}" for t in req.tables))
    dynamic_procs = [p['name'] for p in req.procedures if p.get('is_dynamic')]
    ops_summary   = defaultdict(set)
    for t in req.tables:
        for op in t['ops'].split(', '):
            ops_summary[op.strip()].add(f"{t['schema']}.{t['table']}")

    ops_text = '\n'.join(
        f"  - {op}: {', '.join(sorted(tables))}"
        for op, tables in sorted(ops_summary.items()) if op
    )

    schema_text = ''
    for schema, tables in req.schema_map.items():
        schema_text += f"\nSchema [{schema}]:\n"
        for tbl, info in tables.items():
            cols_preview = ', '.join(info['cols'][:5])
            if len(info['cols']) > 5:
                cols_preview += f" ... +{len(info['cols'])-5} more"
            schema_text += f"  - {tbl}: ops=[{info['ops']}] cols=[{cols_preview}]\n"

    focus = f"\nFocus especially on procedure: {req.focus_proc}" if req.focus_proc else ""

    prompt = f"""Analyze this stored procedure extraction report and provide a concise migration risk assessment.

EXTRACTION SUMMARY:
- Procedures analyzed: {len(req.procedures)}
- Physical tables: {total_tables}
- Schemas involved: {', '.join(schemas)}
- Dynamic SQL detected in: {', '.join(dynamic_procs) if dynamic_procs else 'None'}

OPERATIONS BY TABLE:
{ops_text}

SCHEMA DETAILS:
{schema_text}
{focus}

Provide:
1. MIGRATION COMPLEXITY: (Low/Medium/High) with one-sentence justification
2. TOP 3 RISKS: specific risks based on the tables and operations above
3. RECOMMENDED MIGRATION ORDER: which schemas/tables to migrate first and why
4. WATCH POINTS: any patterns that need manual review before migration

Be specific, reference actual table and schema names from the data. Keep response under 350 words."""

    try:
        response = requests.post(
            HF_API_URL,
            headers={"Authorization": f"Bearer {HF_TOKEN}"},
            json={
                "model":    HF_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a senior database migration architect."},
                    {"role": "user",   "content": prompt},
                ],
                "max_tokens":  500,
                "temperature": 0.3,
            },
            timeout=60
        )
        response.raise_for_status()
        result = response.json()

        choices = result.get('choices') or []
        if not choices:
            raise ValueError(f"no choices in response: {result}")
        text = choices[0]['message']['content']

        return {
            "status":  "success",
            "insight": text.strip(),
            "model":   HF_MODEL,
            "focus":   req.focus_proc
        }

    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="HuggingFace API timeout. Model may be loading — retry in 30s.")
    except requests.exceptions.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"HuggingFace API error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI insight generation failed: {str(e)}")


@app.post("/ai-insights/proc")
async def ai_insights_single_proc(
    files: list[UploadFile] = File(...),
    proc_name: str = Form(default="")
):
    """
    Convenience endpoint: upload files + proc name, get AI insight in one call.
    Used when user checks 'Get AI Insights' checkbox on a specific procedure.
    """
    # First analyze
    analysis = await analyze(files)

    # Then get insight focused on that proc
    req = AIInsightRequest(
        procedures = analysis['procedures'],
        tables     = analysis['tables'],
        columns    = analysis['columns'],
        schema_map = analysis['schema_map'],
        focus_proc = proc_name or None
    )
    return await ai_insights(req)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
