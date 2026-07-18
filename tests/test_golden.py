"""
LAYER 2 — GOLDEN FILE REGRESSION TESTS

This is the safety net for "any new change must first pass through existing
features". Each fixture has a committed golden snapshot of the parser's exact
output. Any change to the parser that alters output for existing fixtures fails
here — loudly, with a diff.

That failure is not automatically a bug. It is a prompt to answer:
  "Did I intend to change this output, and is the new output better?"

If yes:  regenerate with `pytest --update-golden` and COMMIT THE DIFF.
         Reviewers read the golden diff to see the real behavioural change.
If no:   you just caught a regression before it shipped. Fix the code.

The golden diff in a PR is the most valuable artifact in this repo — it shows
exactly how a code change affects real-world SQL analysis.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import parse_sp
from conftest import sql_fixture, GOLDEN

FIXTURES_UNDER_GOLDEN = [
    "multi_cte_report.sql",
    "crud_and_dynamic.sql",
    "alias_collision.sql",
    "postgres_proc.sql",
]


def serialize(physical: dict, dynamic: bool) -> dict:
    """Deterministic, diff-friendly JSON of a parse result."""
    return {
        "dynamic_sql": dynamic,
        "tables": {
            key: {
                "schema": info["schema"],
                "base": info["base"],
                "ops": sorted(info["ops"]),
                "aliases": sorted(info["aliases"]),
                "columns": sorted(info["columns"]),
            }
            for key, info in sorted(physical.items())
        },
    }


def golden_path(fixture: str) -> Path:
    return GOLDEN / f"{fixture.replace('.sql', '')}.json"


@pytest.mark.parametrize("fixture", FIXTURES_UNDER_GOLDEN)
def test_golden_snapshot(fixture, request):
    sql = sql_fixture(fixture)
    physical, dynamic = parse_sp(sql)
    actual = serialize(physical, dynamic)

    path = golden_path(fixture)
    update = request.config.getoption("--update-golden")

    if update or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(actual, indent=2) + "\n", encoding="utf-8")
        if not update:
            pytest.skip(f"created missing golden: {path.name} — review and commit it")
        return

    expected = json.loads(path.read_text(encoding="utf-8"))

    if actual != expected:
        diff = _describe_diff(expected, actual)
        pytest.fail(
            f"\nParser output changed for {fixture}\n"
            f"{diff}\n"
            f"If this change is INTENDED: run `pytest --update-golden` and commit "
            f"the golden diff so reviewers can see the behavioural change.\n"
            f"If NOT intended: you just caught a regression."
        )


def _describe_diff(expected: dict, actual: dict) -> str:
    lines = []
    if expected.get("dynamic_sql") != actual.get("dynamic_sql"):
        lines.append(f"  dynamic_sql: {expected.get('dynamic_sql')} -> {actual.get('dynamic_sql')}")

    exp_t, act_t = expected.get("tables", {}), actual.get("tables", {})
    for gone in sorted(set(exp_t) - set(act_t)):
        lines.append(f"  TABLE LOST:  {gone}")
    for added in sorted(set(act_t) - set(exp_t)):
        lines.append(f"  TABLE ADDED: {added}")

    for key in sorted(set(exp_t) & set(act_t)):
        e, a = exp_t[key], act_t[key]
        for field in ("ops", "aliases", "columns"):
            lost = set(e[field]) - set(a[field])
            added = set(a[field]) - set(e[field])
            if lost:
                lines.append(f"  {key}.{field} LOST:  {sorted(lost)}")
            if added:
                lines.append(f"  {key}.{field} ADDED: {sorted(added)}")

    return "\n".join(lines) or "  (structural difference — inspect the golden file)"
