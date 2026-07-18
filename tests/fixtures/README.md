# Fixtures — provenance rules

**Every fixture in this directory is fictional.** Read this before adding one.

## The rule

Never commit SQL derived from an employer, client, or any system you do not own
the rights to publish. Not "renamed". Not "mostly changed". **Rewritten.**

A schema is intellectual property. Table names, column names, the shape of the
joins, and the vendor systems they imply are all disclosive — even with the
company name stripped. `AcmeRiskDetails` renamed to `RiskDetails` still tells a
reader which vendor package produced it and how that firm models risk.

## What we actually need from a fixture

The parser does not care what things are called. It cares about **structure**:

- multi-CTE chains, CTE referencing another CTE
- `[Bracketed Multi Word]` identifiers
- 3-part `db.schema.table` references
- alias reuse across statements
- `WITH (NOLOCK)`, quoted string aliases, dialect quirks
- encodings, comment styles, dynamic SQL

**Keep the structure. Invent everything else.**

## How to contribute a hard case safely

1. Identify the *structural pattern* that broke the parser.
2. Rebuild that pattern from scratch on a fictional domain
   (`dbo.Party`, `sales.Product`, `risk.RatingDetails`, `refdata.*`).
3. Verify it still reproduces the bug.
4. Add a header comment stating it is fictional and listing what it exercises.
5. Generate the golden, **read it**, then commit.

If you cannot reproduce the bug without the original names, open an issue
describing the pattern in prose instead. We will build the fixture.

## Checklist before committing any fixture

- [ ] No employer, client, or vendor product names
- [ ] No ticket/JIRA IDs, internal codenames, or region/desk names
- [ ] No real people, accounts, or identifiers
- [ ] Header comment says FICTIONAL and lists what it exercises
- [ ] Golden file read by a human, not just generated
