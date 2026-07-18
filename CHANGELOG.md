# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · [SemVer](https://semver.org/).

## [1.0.0] — Unreleased

First public release.

### Added
- Deterministic SQL parser: physical tables, columns, CRUD ops, aliases per stored procedure
- CTE chain resolution (single-hop) and per-statement alias scoping
- `[Bracketed Multi Word]` identifier support
- Multi-encoding reader — UTF-8, Windows-1252, CP1252, Latin-1
- Dialect auto-detection — T-SQL, PostgreSQL, MySQL, Oracle PL/SQL
- FastAPI backend: `GET /health`, `POST /analyze`, `POST /ai-insights`
- Single-file browser UI with 5 tabs and Excel export (SheetJS)
- Opt-in AI migration risk narrative via HuggingFace Mistral-7B
- Report metadata (tool version, UTC timestamp, tier) on every response
- Free/enterprise tier limits (`limits.py`)
- Five-layer test suite — 68 tests, 4 tracked limitations ([TEST_PLAN.md](TEST_PLAN.md))

### Fixed
- **String literals are now masked before extraction.** Previously
  `WHERE Notes = 'migrated FROM dbo.Phantom'` invented a table that does not
  exist, violating the never-invent contract. The same bug caused tables to be
  scraped out of dynamic SQL string literals while simultaneously flagging that
  SQL as unanalyzable — two claims that cannot both be true.

### Known limitations
See [README](README.md#honest-limitations). Each is pinned by a strict-xfail test.
