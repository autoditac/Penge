# Household integration verification

The household release candidate is assembled locally for epic #329.
This checkpoint is not a deployment or a claim that all acceptance gates passed.
All fixtures are synthetic.

## Integrated scope

Foundation categorization and its UTC payment-detail timestamp fix are integrated.
PayPal imports only payment-detail enrichment, never a second transaction ledger.
The public NSI reference index, report API/dbt/MCP projection, and household WebUI
are integrated, including public reference status/search and explicit linking.
ADR-0050 covers categorization, ADR-0051 the user-approved NSI source, and
ADR-0052 reporting.

Shared patch conflicts preserve the stricter integration database guards.
The combined OpenAPI specification and TypeScript client are generated together
after route assembly.
The Prettier hook uses the same pinned version as the WebUI workspace so that
generated and handwritten TypeScript types do not alternate between formats.
Public reference provenance never authorizes changing private classifications.

## Local verification

Run `just household-in-memory-test` for the allowed local suite.
Its database-backed fixtures use only ephemeral in-memory SQLite.
Reporting route tests use synthetic data-layer substitutes; they do not establish
that PostgreSQL queries or dbt materialization work.
The API journey exercises real foundation routes and services, exact nested splits,
deterministic audit selection and undo, learned merchant rules, protected manual
decisions, stale preview rejection, and explicit history approval.
PayPal tests verify repeat-sync/re-consent identity and bank-led conservation.
Vendor tests verify bounded public downloads, privacy, and generation promotion.

Run `just household-dbt-parse` for project parsing without a database build.
WebUI and MCP lint, build, and synthetic tests remain separate checks.
Pinned `@playwright/test` is required because Vitest/jsdom cannot verify real
desktop/mobile layout, navigation, and requests against the running API.
CI runs `just household-browser-seed` and `just household-browser-test` against
its disposable database; these recipes are not authorized for shared local data.
Passing those checks does not establish browser behavior against a materialized
report API.

## Outstanding acceptance gates

The `just household-test` recipe requires a separately authorized disposable
PostgreSQL database and destructive-test opt-in.
Do not run it against a shared database.
CI must verify migration upgrade/downgrade, household report mart invariants,
unchanged original marts, and the real database-backed API paths.
Full browser verification must use synthetic data and real Penge APIs on desktop
and mobile, not client-side mock reports.

Personal PayPal entitlement, consent, actual provider fields, and history depth
remain unverified.
A public ASPSP listing does not prove live access.
Signing, pushing, opening a PR, merging, and deploying are separately gated.
Keep the epic and child issues open until their acceptance criteria are satisfied.
