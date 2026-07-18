"""
LAYER 3 — KNOWN LIMITATIONS (xfail)

Every test here documents a real, reproducible defect we have chosen not to fix
yet. They are marked `xfail(strict=True)`, which means:

  - While the defect exists, the test "fails as expected" and CI stays green.
  - The DAY SOMEONE FIXES IT, the test XPASSes and CI turns RED — forcing the
    fixer to promote it to a real assertion in test_regressions.py.

This is how we keep an honest, machine-checked list of what the tool gets wrong.
Nothing rots silently. The README's "Honest limitations" table must stay in sync
with this file.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import parse_sp
from conftest import cols_of, tables_of


@pytest.mark.xfail(strict=True, reason="KL-1: output aliases are reported as physical columns")
def test_KL1_cte_output_alias_not_reported_as_physical_column():
    """
    `SELECT Id as 'Party ID' FROM dbo.Party` means dbo.Party has a
    column `Id`. It does NOT have a column called `Party ID` — that is an
    output alias.

    We currently report both, which sends a BSA looking for a column that does
    not exist in the source schema. Fixing this requires tracking alias->source
    column bindings, which regex cannot do reliably — this is the strongest
    argument for the planned AST backend (see ROADMAP).
    """
    sql = """
    ;WITH PartyDetails AS (SELECT Id as 'Party ID' FROM dbo.Party)
    SELECT LE.[Party ID] FROM PartyDetails LE
    """
    physical, _ = parse_sp(sql)
    cols = cols_of(physical, "DBO.PARTY")
    assert "ID" in cols, "the real source column must be reported"
    assert "Party ID" not in cols, "the output alias must NOT be reported as a physical column"


@pytest.mark.xfail(strict=True, reason="KL-2: display casing is inconsistent between bracketed and plain identifiers")
def test_KL2_identifier_casing_is_consistent():
    """
    `dbo.Alpha` renders as ALPHA, `[dbo].[Bravo]` renders as Bravo. Cosmetic,
    but it looks sloppy in an enterprise report and makes Excel sorting odd.
    """
    sql = "SELECT a.Id FROM dbo.Alpha a INNER JOIN [dbo].[Bravo] b ON b.Id = a.Id"
    physical, _ = parse_sp(sql)
    bases = [v["base"] for v in physical.values()]
    assert all(b.isupper() for b in bases) or all(not b.isupper() for b in bases), \
        f"inconsistent casing: {bases}"


@pytest.mark.xfail(strict=True, reason="KL-3: multi-hop CTE chains do not fully resolve")
def test_KL3_multi_hop_cte_chain_resolves():
    """
    Country CTE sources FROM PartyRef (another CTE) which sources FROM dbo.PartyCompany.
    Columns referenced via the Country alias should reach dbo.PartyCompany.
    """
    sql = """
    ;WITH PartyRef AS (SELECT PartyId, CountryOfIncorporationId FROM dbo.PartyCompany),
    Country AS (SELECT c.Id, c.ShortName FROM PartyRef INNER JOIN dbo.Country c ON c.id = PartyRef.CountryOfIncorporationId)
    SELECT ctry.ShortName FROM Country ctry
    """
    physical, _ = parse_sp(sql)
    assert "SHORTNAME" in cols_of(physical, "DBO.COUNTRY")


@pytest.mark.xfail(strict=True, reason="KL-4: dynamic SQL table names are unknowable statically")
def test_KL4_dynamic_sql_tables_extracted():
    """
    Will never pass without executing the SQL. Kept as a permanent marker that
    this is a deliberate design boundary, not an oversight. If this ever
    XPASSes, someone added runtime execution — that is a security review.
    """
    sql = "DECLARE @s NVARCHAR(MAX) = N'SELECT * FROM dbo.SecretTable'; EXEC sp_executesql @s;"
    physical, _ = parse_sp(sql)
    assert "DBO.SECRETTABLE" in tables_of(physical)
