"""
LAYER 5 — API CONTRACT TESTS

The UI and any third-party integration depend on the JSON shape. These tests
pin the API contract. Breaking one of these is a breaking change requiring a
major version bump — the UI is decoupled precisely so it can rely on this.
"""
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

FIXTURES = Path(__file__).parent / "fixtures"


def upload(name: str):
    return ("files", (name, io.BytesIO((FIXTURES / name).read_bytes()), "text/plain"))


# ── Health ────────────────────────────────────────────────────────────────────

def test_health_shape(client):
    r = client.get("/health")
    assert r.status_code == 200
    d = r.json()
    for field in ("status", "version", "hf_configured", "tier", "limits"):
        assert field in d, f"/health missing {field}"
    assert d["status"] == "ok"


def test_health_publishes_limits(client):
    """Clients must be able to discover limits without trial and error."""
    limits = client.get("/health").json()["limits"]
    for field in ("max_files_per_request", "max_file_bytes", "max_tables_per_request"):
        assert field in limits


def test_root_reports_version(client):
    d = client.get("/").json()
    assert "version" in d


# ── Analyze happy path ────────────────────────────────────────────────────────

def test_analyze_returns_full_contract(client):
    r = client.post("/analyze", files=[upload("multi_cte_report.sql")])
    assert r.status_code == 200, r.text
    d = r.json()
    for field in ("status", "meta", "procedures", "tables", "columns", "schema_map", "stats"):
        assert field in d, f"/analyze missing {field}"
    assert d["status"] == "success"


def test_analyze_meta_is_auditable(client):
    """Enterprise requirement: every report is traceable to a tool version+time."""
    meta = client.post("/analyze", files=[upload("crud_and_dynamic.sql")]).json()["meta"]
    for field in ("tool", "version", "generated_at", "files", "tier"):
        assert field in meta, f"meta missing {field}"
    assert meta["tool"] == "sql-sp-companion"
    assert "crud_and_dynamic.sql" in meta["files"]


def test_analyze_stats_are_internally_consistent(client):
    d = client.post("/analyze", files=[upload("crud_and_dynamic.sql")]).json()
    stats = d["stats"]
    assert stats["total_procedures"] == len(d["procedures"])
    assert stats["total_schemas"] == len(d["schema_map"])
    distinct = {f"{t['schema']}.{t['table']}" for t in d["tables"]}
    assert stats["total_tables"] == len(distinct)


def test_analyze_row_shapes(client):
    d = client.post("/analyze", files=[upload("multi_cte_report.sql")]).json()
    for t in d["tables"]:
        assert set(t) >= {"proc", "file", "schema", "table", "ops", "aliases"}
    for c in d["columns"]:
        assert set(c) >= {"proc", "file", "schema", "table", "col", "ops"}


def test_analyze_flags_dynamic_sql_in_response(client):
    d = client.post("/analyze", files=[upload("crud_and_dynamic.sql")]).json()
    assert d["stats"]["dynamic_sql_count"] >= 1
    assert any(p["is_dynamic"] for p in d["procedures"])


def test_analyze_multiple_files(client):
    r = client.post("/analyze", files=[
        upload("alias_collision.sql"),
        upload("postgres_proc.sql"),
    ])
    assert r.status_code == 200
    files_seen = {t["file"] for t in r.json()["tables"]}
    assert files_seen == {"alias_collision.sql", "postgres_proc.sql"}


# ── Tier enforcement at the HTTP layer ────────────────────────────────────────

def test_analyze_rejects_over_file_count_with_413(client, free_tier):
    files = [upload("alias_collision.sql") for _ in range(6)]
    r = client.post("/analyze", files=files)
    assert r.status_code == 413
    detail = r.json()["detail"]
    assert detail["error"] == "tier_limit_exceeded"
    assert detail["limit"] == "max_files_per_request"
    assert detail["tier"] == "free"


def test_tier_limit_error_is_machine_readable(client, free_tier):
    """The UI needs to render an upgrade prompt, not a stack trace."""
    r = client.post("/analyze", files=[upload("alias_collision.sql") for _ in range(9)])
    detail = r.json()["detail"]
    for field in ("error", "message", "limit", "limit_value", "actual", "tier"):
        assert field in detail, f"limit error missing {field}"


def test_analyze_rejects_oversized_file(client, free_tier):
    big = b"SELECT x.Id FROM dbo.T x;\n" * 60_000  # > 1MB
    r = client.post("/analyze", files=[("files", ("big.sql", io.BytesIO(big), "text/plain"))])
    assert r.status_code == 413
    assert r.json()["detail"]["limit"] == "max_file_bytes"


# ── AI endpoint is opt-in and fails safe ──────────────────────────────────────

def test_ai_insights_requires_token_and_says_so(client, monkeypatch):
    import main
    monkeypatch.setattr(main, "HF_TOKEN", "")
    r = client.post("/ai-insights", json={
        "procedures": [], "tables": [], "columns": [], "schema_map": {},
    })
    assert r.status_code == 503
    assert "hf_token" in r.json()["detail"].lower() or "token" in r.json()["detail"].lower()


def test_analyze_never_calls_ai(client, monkeypatch):
    """The core analysis path must work with zero AI configuration."""
    import main
    monkeypatch.setattr(main, "HF_TOKEN", "")

    def boom(*a, **k):
        raise AssertionError("/analyze made an outbound HTTP call")

    monkeypatch.setattr(main.requests, "post", boom)
    r = client.post("/analyze", files=[upload("multi_cte_report.sql")])
    assert r.status_code == 200
