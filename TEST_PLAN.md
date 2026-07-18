# Test Plan — sql-sp-companion

**Purpose:** every change must prove it did not break what already worked.
This document defines how that is enforced, not aspirationally, but in CI.

**Status:** 68 passing · 4 tracked limitations (xfail) · CI-gated on every PR

---

## 1. Testing philosophy

This is a static analyzer whose entire value proposition is **trust**. A BSA
plans a migration around our output. If we silently miss a table, they discover
it during a production cutover at 2am. That risk profile dictates the strategy:

| Principle | Consequence |
|---|---|
| **Wrong output is worse than no output** | Contract tests forbid guessing/inventing |
| **Every fixed bug stays fixed** | Every bug becomes a permanent regression test |
| **Behaviour changes must be visible** | Golden files make output diffs reviewable |
| **Known defects must not rot silently** | Limitations are `xfail(strict=True)`, not TODOs |
| **The parser is offline** | Tests assert zero network calls in the extraction path |

**We do not chase coverage percentage.** Coverage measures lines executed, not
promises kept. We measure whether the contracts hold on real SQL.

---

## 2. Test architecture — five layers

Run all: `pytest tests/ -v`

```
tests/
├── conftest.py                 fixtures, --update-golden flag
├── fixtures/*.sql              real-world SQL inputs (sanitized)
├── golden/*.json               committed output snapshots
│
├── test_contracts.py           LAYER 1 — non-negotiable promises      (18)
├── test_golden.py              LAYER 2 — output regression gate        (4)
├── test_known_limitations.py   LAYER 3 — tracked defects (xfail)       (4)
├── test_tiers.py               LAYER 4 — commercial boundary          (17)
├── test_api.py                 LAYER 5 — HTTP contract                (16)
└── test_parser.py              unit regressions — one per fixed bug   (13)
```

### Layer 1 — Contract tests (`test_contracts.py`)

Six promises. Breaking one means the tool is lying to its users.

| ID | Contract | Why it exists |
|---|---|---|
| **C1** | Determinism — 5 runs, identical output | Our core differentiator vs LLM tools |
| **C2** | Physical objects only — no temp tables, no CTE names | Product definition |
| **C3** | No silent drops — bad bytes never truncate | The SSMS `0x95` incident |
| **C4** | No guessing — ambiguous cols unresolved, never invented | Trust |
| **C5** | Dynamic SQL always flagged | Honesty about our boundary |
| **C6** | Zero network calls during parsing | Enterprise data governance |

**Rule: never weaken a contract assertion to make a feature pass.** Changing a
contract is a major version bump, discussed in an issue, with a README change.

### Layer 2 — Golden files (`test_golden.py`)

This is the mechanism that answers *"does my change break existing features?"*

Each fixture has a committed JSON snapshot of exact parser output. Any change
that alters output for existing fixtures **fails loudly with a structured diff**:

```
Parser output changed for multi_cte_report.sql
  TABLE LOST:  RISK.RATINGDETAILS
  DBO.PARTY.columns ADDED: ['ACTIVE']
```

That failure is a **question, not a verdict**: did I intend this, and is it better?

```bash
# Intended change → regenerate and COMMIT THE DIFF
pytest --update-golden
git add tests/golden/ && git commit   # reviewers read the diff
```

**The golden diff is the most valuable artifact in a PR.** It shows precisely how
a code change affects real-world SQL analysis. A parser PR with no golden diff
changed nothing; a PR with a golden diff must explain it.

### Layer 3 — Known limitations (`test_known_limitations.py`)

Real defects we have chosen not to fix, marked `xfail(strict=True)`:

- While the defect exists → "expected failure", CI green.
- **The day it is fixed → XPASS → CI turns RED**, forcing the fixer to promote it
  to a real assertion.

Nothing rots silently. The README limitations table must stay in sync with this file.

| ID | Defect | Fix path |
|---|---|---|
| **KL-1** | CTE output aliases reported as physical columns | Needs AST backend |
| **KL-2** | Casing inconsistent between `[Bracketed]` and plain identifiers | Cosmetic, v1.1 |
| **KL-3** | Multi-hop CTE chains don't fully resolve | Needs AST backend |
| **KL-4** | Dynamic SQL tables not extracted | **Permanent by design** — XPASS here means someone added runtime execution, which is a security review |

### Layer 4 — Tier tests (`test_tiers.py`)

The free/enterprise boundary is a public promise. Free limits silently tightening
kills community trust; silently loosening kills the business model. These pin it
so any change is deliberate and reviewed.

Includes `test_free_tier_handles_a_realistic_evaluation_workload` — a guard that
the free tier stays a *product*, not a demo.

### Layer 5 — API tests (`test_api.py`)

The UI and third-party integrations depend on JSON shape. Breaking these is a
breaking change requiring a major version bump — the UI is decoupled precisely
so it can rely on this contract.

Also asserts `/analyze` works with **zero AI configuration** and makes no outbound
HTTP calls.

---

## 3. The workflow for any change

```
 1. Write a FAILING test first
      parser bug     → tests/test_parser.py
      new capability → tests/test_parser.py + new fixture
      API change     → tests/test_api.py

 2. Run the full suite — see it fail for the right reason
      pytest tests/ -v

 3. Make the change

 4. Run the full suite again
      ✅ all green, no golden diff  → change is additive, ship it
      ⚠️  golden diff               → STOP. Read the diff.
                                      Intended & better? --update-golden, commit diff.
                                      Not intended?      you caught a regression.
      ❌ contract test fails        → STOP. Do not weaken the assertion.
      ❌ xfail XPASSed              → you fixed a known limitation.
                                      Promote it to a real test. Update README.

 5. PR must include:
      - the new test
      - the golden diff (if any) with an explanation
      - README limitations update (if KL status changed)
```

**No PR merges with a red suite. No exceptions, including "just a docs change" —
because "just a docs change" is exactly when someone slips in a parser tweak.**

---

## 4. Adding a fixture

Fixtures are **real-world SQL, sanitized** — not toy queries. Toy SQL passes;
production SQL is where parsers die.

```bash
# 1. Sanitize: rename tables/columns, keep the STRUCTURE that broke us
vim tests/fixtures/my_hard_case.sql

# 2. Register it for golden coverage
#    tests/test_golden.py → add to FIXTURES_UNDER_GOLDEN
#    tests/test_contracts.py → add to the C1 determinism parametrize list

# 3. Generate + REVIEW the golden by hand before committing
pytest --update-golden
cat tests/golden/my_hard_case.json    # is this output actually correct?
```

**Step 3 review is mandatory.** A golden file generated from buggy output pins
the bug in place forever. The golden is only as good as the human who read it.

---

## 5. What the suite deliberately does not test

Honest scope boundaries:

| Not tested | Why | Mitigation |
|---|---|---|
| HuggingFace response quality | Third-party model, non-deterministic | Test the call contract + failure modes only |
| Excel byte-level formatting | SheetJS is a dependency; testing it tests them | Test the data going in |
| UI rendering | No browser in CI; adding one costs more than it catches | Manual check before release |
| Real database connections | Tool is file-based by design (a feature, not a gap) | N/A |
| Performance at 10k files | No enterprise-scale corpus yet | **Gap — v1.1 with batch CLI** |

---

## 6. CI

`.github/workflows/ci.yml` — every push and PR, Python 3.11 + 3.12:

```yaml
- pytest tests/ -v        # all layers
- import smoke test       # app boots
```

Required before merge. Branch protection enforces it.

---

## 7. Release checklist

- [ ] `pytest tests/ -v` green on 3.11 and 3.12
- [ ] No unexplained golden diffs
- [ ] xfail list matches README "Honest limitations" table
- [ ] `__version__` bumped in `main.py`
- [ ] Tier limits unchanged, or README + pricing updated in the same commit
- [ ] Manual UI check: upload → 5 tabs → Excel download
