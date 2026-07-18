# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.x     | ✅        |

## Data handling

- **/analyze**: SQL files are processed in memory and never persisted to disk
  by the backend. No SQL content is logged.
- **/ai-insights** (opt-in only): schema metadata (table names, schema names,
  operation types, column name previews) is sent to the HuggingFace Inference
  API. **SQL source code is never sent to any third party.** This endpoint is
  disabled unless the `HF_TOKEN` environment variable is set, and the UI
  requires an explicit user opt-in checkbox per session.
- The reference deployment (`main.py`) restricts CORS to the known UI
  origins (`https://sql-sp-companion.vercel.app`, `http://localhost:8000`,
  and `null` for `file://`). **If you fork this and host your own UI,
  update `allow_origins` to your UI's domain before any production
  deployment.**

## Reporting a vulnerability

Please report vulnerabilities privately via GitHub Security Advisories on this
repository (Security tab → Report a vulnerability). Do not open public issues
for security reports.

You can expect an acknowledgment within 72 hours and a fix or mitigation plan
within 14 days for confirmed issues.
