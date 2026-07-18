# Contributing to sql-sp-companion

Thanks for your interest in contributing! This project welcomes issues, PRs,
and test cases — especially real-world SQL patterns the parser gets wrong.

## The most valuable contribution: failing SQL

If the parser misses a table or misattributes a column, open an issue with:

1. A **minimal SQL snippet** that reproduces it (sanitize table/column names)
2. What the parser returned
3. What you expected

We turn every confirmed bug into a regression test in `tests/test_parser.py`.

## Development setup

```bash
git clone https://github.com/AutoShiftOps/sql-sp-companion
cd sql-sp-companion
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install pytest

# Run the backend
uvicorn main:app --reload

# Run tests (required before any PR)
python -m pytest tests/ -v
```

Open `index.html` in a browser and point the API bar at `http://localhost:8000`.

## Pull request guidelines

- **One change per PR.** Parser fix, UI change, and docs update are three PRs.
- **Every parser change needs a test.** If you fix an extraction bug, add the
  failing case to `tests/test_parser.py` first, then make it pass.
- **Don't break determinism.** The parser must produce identical output for
  identical input. No randomness, no LLM calls in the extraction path.
- **UI stays a single file.** `index.html` is intentionally framework-free and
  build-free. Don't introduce npm/webpack/React.
- **Backend and UI are decoupled.** Parser changes must not require UI changes
  and vice versa, unless the API contract itself changes (discuss in an issue
  first).

## Code style

- Python: standard library + FastAPI only in the extraction path. Keep the
  parser dependency-free so it can be vendored into other tools.
- Comment the *why* on regex patterns — future contributors can read regex,
  but not your intent.

## Architecture rules (do not violate without discussion)

| Rule | Reason |
|---|---|
| Temp tables (`#t`) and CTEs never appear in output | They are not physical schema objects |
| Aliases are scoped per-statement | Global alias maps caused real misattribution bugs |
| AI features are opt-in and clearly labeled | Enterprise data-governance requirement |
| File reading never drops bytes | SSMS Windows-1252 exports must fully parse |

## Release process

Maintainers bump `__version__` in `main.py`, tag `vX.Y.Z`, and update the
changelog section in the README.
