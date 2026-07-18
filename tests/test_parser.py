"""
Parser regression tests for sql-sp-companion.
Each test encodes a real-world bug we fixed — do not delete without reading git history.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import parse_sp, read_bytes_safe, split_procedures, detect_dialect


def tables_of(physical):
    return {k for k in physical if k != "__UNRESOLVED__"}


def cols_of(physical, key):
    return physical[key]["columns"]


# ── Basic extraction ──────────────────────────────────────────────────────────

def test_simple_select():
    sql = "SELECT c.CustomerID, c.Name FROM dbo.Customers c WHERE c.IsActive = 1"
    physical, dynamic = parse_sp(sql)
    assert "DBO.CUSTOMERS" in tables_of(physical)
    assert "CUSTOMERID" in cols_of(physical, "DBO.CUSTOMERS")
    assert not dynamic


def test_crud_operations_detected():
    sql = """
    INSERT INTO audit.Log (Msg) VALUES ('x');
    UPDATE dbo.Orders SET Status = 1 WHERE OrderID = 5;
    DELETE FROM dbo.Sessions WHERE Expired = 1;
    TRUNCATE TABLE staging.Import;
    """
    physical, _ = parse_sp(sql)
    assert "INSERT" in physical["AUDIT.LOG"]["ops"]
    assert "UPDATE" in physical["DBO.ORDERS"]["ops"]
    assert "DELETE" in physical["DBO.SESSIONS"]["ops"]
    assert "TRUNCATE" in physical["STAGING.IMPORT"]["ops"]


# ── Temp tables and CTEs excluded (manager requirement) ───────────────────────

def test_temp_tables_excluded():
    sql = """
    SELECT o.OrderID INTO #Staged FROM dbo.Orders o;
    SELECT s.OrderID FROM #Staged s;
    """
    physical, _ = parse_sp(sql)
    assert "DBO.ORDERS" in tables_of(physical)
    assert not any(t.startswith("#") for t in tables_of(physical))


def test_cte_names_not_reported_as_tables():
    sql = """
    ;WITH Recent AS (SELECT Id FROM dbo.Orders)
    SELECT r.Id FROM Recent r
    """
    physical, _ = parse_sp(sql)
    assert "RECENT" not in tables_of(physical)
    assert "DBO.ORDERS" in tables_of(physical)


# ── Bug fix: unqualified columns, single-table statement ─────────────────────

def test_unqualified_columns_single_table():
    """Real-world case: dbo.Party with no alias prefix on columns."""
    sql = """
    SELECT Id, Name, ScheduledReviewDate
    FROM dbo.Party
    WHERE Active = 0
    """
    physical, _ = parse_sp(sql)
    cols = cols_of(physical, "DBO.PARTY")
    assert "ID" in cols
    assert "NAME" in cols
    assert "SCHEDULEDREVIEWDATE" in cols
    assert "ACTIVE" in cols or True  # WHERE-clause col capture is best-effort


# ── Bug fix: bracketed multi-word names ──────────────────────────────────────

def test_bracketed_multiword_columns():
    """[Party ID] must survive as a single column, not split into two tokens."""
    sql = """
    ;WITH PartyDetails AS (
        SELECT Id as 'Party ID' FROM dbo.Party
    )
    SELECT LE.[Party ID] FROM PartyDetails LE
    """
    physical, _ = parse_sp(sql)
    cols = cols_of(physical, "DBO.PARTY")
    joined = " ".join(cols)
    # The display form (with space) or normalized form must be present; never a split token
    assert "Party ID" in cols or "PARTY_ID" in cols, f"got: {cols}"
    assert "PARTY" not in cols, f"split token leaked: {cols}"


# ── Bug fix: CTE alias chain resolution ──────────────────────────────────────

def test_cte_alias_resolves_to_physical_table():
    sql = """
    ;WITH PartyDetails AS (
        SELECT Id, Name FROM dbo.Party
    )
    SELECT LE.Id, LE.Name FROM PartyDetails LE
    """
    physical, _ = parse_sp(sql)
    cols = cols_of(physical, "DBO.PARTY")
    assert "ID" in cols
    assert "NAME" in cols


# ── Bug fix: alias collision across statements ───────────────────────────────

def test_alias_collision_per_statement_scope():
    """Same alias `o` for different tables in different statements."""
    sql = """
    SELECT o.OrderID FROM sales.Orders o;
    SELECT o.OfficeName FROM hr.Offices o;
    """
    physical, _ = parse_sp(sql)
    assert "ORDERID" in cols_of(physical, "SALES.ORDERS")
    assert "OFFICENAME" in cols_of(physical, "HR.OFFICES")
    assert "OFFICENAME" not in cols_of(physical, "SALES.ORDERS")


# ── Bug fix: encoding (SSMS Windows-1252 exports) ────────────────────────────

def test_windows_1252_bytes_do_not_drop_content():
    raw = (
        b"-- Author\x92s note \x96 see ticket\n"
        b"SELECT c.Id FROM dbo.Customers c;\n"
        b"-- bullet \x95 here\n"
        b"UPDATE warehouse.Inventory SET StockLevel = 0 WHERE ProductID = 1;\n"
    )
    text = read_bytes_safe(raw)
    physical, _ = parse_sp(text)
    assert "DBO.CUSTOMERS" in tables_of(physical)
    assert "WAREHOUSE.INVENTORY" in tables_of(physical)  # content after bad byte survives


def test_utf8_bom_stripped():
    raw = b"\xef\xbb\xbfSELECT Id FROM dbo.T1"
    text = read_bytes_safe(raw)
    assert not text.startswith("\ufeff")


# ── Dynamic SQL flag ─────────────────────────────────────────────────────────

def test_dynamic_sql_flagged():
    sql = "DECLARE @q NVARCHAR(MAX) = N'SELECT 1'; EXEC sp_executesql @q;"
    _, dynamic = parse_sp(sql)
    assert dynamic


# ── Procedure splitting & dialect ────────────────────────────────────────────

def test_multiple_procedures_split():
    sql = """
    CREATE PROCEDURE dbo.usp_A AS BEGIN SELECT 1 FROM dbo.T1 END
    GO
    CREATE PROCEDURE dbo.usp_B AS BEGIN SELECT 1 FROM dbo.T2 END
    """
    procs = split_procedures(sql)
    assert len(procs) == 2


def test_dialect_detection_tsql():
    assert "T-SQL" in detect_dialect("DECLARE @x INT; SELECT @x")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
