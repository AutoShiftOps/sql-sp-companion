"""
LAYER 1 — CONTRACT TESTS

These encode the product's non-negotiable promises. If one of these fails, the
tool is lying to its users. Never delete a test here; never weaken an assertion
here to make a feature pass. If a contract genuinely must change, that is a
major version bump and a README change, discussed in an issue first.

Contracts:
  C1  Determinism        — same input always yields identical output
  C2  Physical-only      — temp tables and CTE names never appear as tables
  C3  No silent drops    — bad bytes never truncate a file
  C4  No guessing        — ambiguous columns are unresolved, never invented
  C5  Dynamic SQL honesty— EXEC/sp_executesql is always flagged
  C6  No AI in parsing   — extraction path makes zero network calls
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import parse_sp, read_bytes_safe
from conftest import sql_fixture, tables_of, cols_of


# ── C1: Determinism ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("fixture", [
    "multi_cte_report.sql",
    "crud_and_dynamic.sql",
    "alias_collision.sql",
    "postgres_proc.sql",
])
def test_C1_parsing_is_deterministic(fixture):
    """Five identical runs must produce byte-identical structures."""
    sql = sql_fixture(fixture)
    runs = []
    for _ in range(5):
        physical, dynamic = parse_sp(sql)
        snapshot = sorted(
            (k, tuple(sorted(v["ops"])), tuple(sorted(v["columns"])))
            for k, v in physical.items()
        )
        runs.append((snapshot, dynamic))
    assert all(r == runs[0] for r in runs), f"{fixture} produced non-deterministic output"


# ── C2: Physical objects only ─────────────────────────────────────────────────

def test_C2_temp_tables_never_reported():
    physical, _ = parse_sp(sql_fixture("crud_and_dynamic.sql"))
    for t in tables_of(physical):
        assert not t.lstrip("[").startswith("#"), f"temp table leaked: {t}"


def test_C2_cte_names_never_reported_as_tables():
    physical, _ = parse_sp(sql_fixture("multi_cte_report.sql"))
    cte_names = {"LEDETAILS", "LEI", "COUNTRY", "REGIONRISKDETAILS",
                 "GROUPRISKRATING", "PRODUCTS"}
    for t in tables_of(physical):
        base = t.split(".")[-1]
        assert base not in cte_names, f"CTE name leaked as table: {t}"


def test_C2_variable_tables_never_reported():
    physical, _ = parse_sp("SELECT x.Id FROM @TableVar x")
    assert not any("@" in t for t in tables_of(physical))


# ── C3: No silent content loss ────────────────────────────────────────────────

def test_C3_bad_bytes_never_truncate_file():
    """The classic SSMS bug: 0x95/0x96 in a comment killed everything after it."""
    raw = (
        b"SELECT a.Id FROM dbo.TableAlpha a;\n"
        b"-- smart quote \x92 en-dash \x96 bullet \x95 accent \xe9\n"
        b"SELECT b.Id FROM dbo.TableBravo b;\n"
        b"-- more junk \x93\x94\n"
        b"SELECT c.Id FROM dbo.TableCharlie c;\n"
    )
    physical, _ = parse_sp(read_bytes_safe(raw))
    found = tables_of(physical)
    for expected in ("DBO.TABLEALPHA", "DBO.TABLEBRAVO", "DBO.TABLECHARLIE"):
        assert expected in found, f"content after bad byte was dropped: missing {expected}"


def test_C3_decoder_preserves_byte_count():
    raw = b"SELECT 1 -- caf\xe9 \x96 test"
    text = read_bytes_safe(raw)
    assert len(text) == len(raw), "decoder changed character count"


# ── C4: Never invent, never guess ─────────────────────────────────────────────

def test_C4_ambiguous_columns_are_not_attributed():
    """Unqualified col in a multi-table SELECT must not be assigned to a table."""
    sql = """
    SELECT SomeAmbiguousColumn
    FROM dbo.TableOne t1
    INNER JOIN dbo.TableTwo t2 ON t2.Id = t1.Id
    """
    physical, _ = parse_sp(sql)
    for key in tables_of(physical):
        assert "SOMEAMBIGUOUSCOLUMN" not in cols_of(physical, key), \
            f"guessed ambiguous column onto {key}"


def test_C4_no_columns_invented_from_nothing():
    sql = "SELECT * FROM dbo.Wildcard w"
    physical, _ = parse_sp(sql)
    assert "DBO.WILDCARD" in tables_of(physical)
    assert cols_of(physical, "DBO.WILDCARD") == set(), "invented columns for SELECT *"


def test_C4_keywords_never_reported_as_columns():
    physical, _ = parse_sp(sql_fixture("multi_cte_report.sql"))
    banned = {"SELECT", "FROM", "WHERE", "INNER", "JOIN", "LEFT", "ORDER", "DISTINCT"}
    for key in tables_of(physical):
        leaked = cols_of(physical, key) & banned
        assert not leaked, f"SQL keywords reported as columns on {key}: {leaked}"


# ── C5: Dynamic SQL honesty ───────────────────────────────────────────────────

@pytest.mark.parametrize("sql", [
    "EXEC('SELECT 1')",
    "EXECUTE('SELECT 1')",
    "EXEC sp_executesql @q",
    "DECLARE @s NVARCHAR(MAX); EXEC sp_executesql @s",
])
def test_C5_dynamic_sql_always_flagged(sql):
    _, dynamic = parse_sp(sql)
    assert dynamic, f"failed to flag dynamic SQL: {sql}"


def test_C5_static_sql_not_falsely_flagged():
    _, dynamic = parse_sp("SELECT c.Id FROM dbo.Customers c")
    assert not dynamic


# ── C6: Extraction path is offline ────────────────────────────────────────────

def test_C6_parsing_makes_no_network_calls(monkeypatch):
    """The parser must never phone home. AI is a separate, opt-in endpoint."""
    import socket

    def boom(*args, **kwargs):
        raise AssertionError("parser attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", boom)
    physical, _ = parse_sp(sql_fixture("multi_cte_report.sql"))
    assert tables_of(physical), "parser produced no output"
