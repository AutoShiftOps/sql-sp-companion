# Licensing & Commercial Model

## TL;DR

The code in this repository is **Apache-2.0**. All of it. Forever.

There are free-tier limits in `limits.py`. **You can legally delete them.**
We know. That is not a bug in our thinking — it is a deliberate choice, and
this document explains why.

---

## The honest tension

We ship free-tier limits (5 files, 1 MB/file, 50 tables) inside an Apache-2.0
codebase. Apache-2.0 grants you the right to modify and redistribute. So any
competent engineer can delete five constants, rebuild, and have an unlimited
build. There is no DRM here and there never will be.

Anyone who tells you otherwise about an Apache-2.0 project is selling something.

## So why have limits at all?

**The limits are a signpost, not a fence.**

They make the free/paid boundary explicit and honest for the large majority of
users who want to comply — enterprises, in particular, do not ship forked
builds of tools with the limits hacked out, because their legal and procurement
teams will not sign off on it. The limit exists so a BSA at a bank knows,
without reading a pricing page, that analyzing 3,000 stored procedures is a
commercial use.

For everyone else — students, individual contributors, open-source projects,
someone evaluating on a weekend — the free tier is **deliberately generous
enough to do real work**. There is a test (`test_free_tier_handles_a_realistic_evaluation_workload`)
that fails if we ever make the free tier a crippled demo.

## Where the real commercial value lives

Not in the constants. In things that are hard to fork:

| Free (Apache-2.0, this repo) | Enterprise (commercial) |
|---|---|
| Full parser engine, unlimited if you fork it | **Hosted service** with SLA |
| Self-hosted, self-supported | **Support contract**, response SLA |
| Bring your own HuggingFace token | **Air-gapped AI** (local Ollama/Bedrock in your VPC) |
| JSON + Excel output | **Purview / Collibra / Atlas connectors** |
| Community issues | **Indemnification, security attestation, SOC2 artifacts** |
| — | **Batch CLI at estate scale + audit ledger** |

An enterprise buying this is not buying the removal of a `50`. They are buying
someone to call at 2am during a cutover, and a signed statement that the tool
did not phone home. Neither is forkable.

## Why Apache-2.0 and not BSL / Elastic / SSPL

We considered source-available licenses that would make the limits legally
binding (BSL 1.1 with a 4-year Apache conversion, or Elastic License 2.0).

**We chose Apache-2.0 anyway:**

- **Adoption is the whole strategy.** This tool competes against AWS SCT, which
  is *free*. A restrictive license against a free incumbent is a losing hand.
- **Enterprises can actually use it.** Apache-2.0 clears legal review at banks
  without a conversation. BSL does not — it triggers a review that most teams
  will not bother starting.
- **Patent grant.** Apache-2.0's explicit patent grant is why we chose it over
  MIT. In a space with a 20-year commercial incumbent holding parser patents,
  that grant is meaningful protection for our users and contributors.
- **Contributor trust.** People contribute parser fixes to Apache-2.0 projects.
  They do not contribute to a codebase where the license reserves commercial
  rights to one company.

If someone forks this, strips the limits, and runs it internally — good. That
is a user who was never going to pay, now getting value, and possibly filing a
bug report that makes the parser better for everyone.

If someone forks this and sells it as a competing hosted service — that is the
real risk Apache-2.0 accepts. We accept it because at our current scale,
obscurity is a bigger threat than competition.

**This decision is revisitable.** If a hyperscaler ships our parser as a managed
service, we will reconsider the license for *future* versions. Everything
released to date stays Apache-2.0 permanently — that promise is not revisitable.

## What is NOT in this repo

The enterprise license key verification logic lives in a separate proprietary
package. `limits._validate_license_key()` here is a placeholder that checks a
prefix. This is intentional: the core does not contain the signing keys or the
verification algorithm, so the Apache-2.0 code can be audited fully without
exposing the commercial mechanism.

## Free tier, precisely

| Limit | Free | Enterprise |
|---|---|---|
| Files per request | 5 | unlimited |
| Bytes per file | 1 MB | 100 MB |
| Bytes per request | 5 MB | 2 GB |
| Distinct tables reported | 50 | unlimited |
| AI insights (your own token) | ✅ | ✅ |
| Batch API / CLI | ❌ | ✅ |
| Hosted, SLA, support | ❌ | ✅ |

Pinned by tests in `tests/test_tiers.py`. Changing any number requires updating
those tests, this file, and the README in the same commit.

---

*Questions about commercial use: open a GitHub Discussion. We would rather have
the conversation in public.*
