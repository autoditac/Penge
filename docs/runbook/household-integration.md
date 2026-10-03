# Household integration verification

The household release candidate is published as draft PR #335 for epic #329.
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
CI also runs `just household-mcp-postgres-test` against the seeded marts.
This opt-in check uses the actual read-only PostgreSQL runner, not a fake runner,
to verify positional SQL parameters across day/month/year report granularity.
Unit tests and browser discovery alone do not establish real report behavior.

Household database acceptance builds the full dbt graph, including relationship
test targets outside the selected reporting ancestors.
No integrity tests are suppressed.
Fixture migrations run in a child process so Alembic cannot disable loggers or
replace pytest's log-capture handlers in subsequent tests.
Synthetic transfer descriptions carry the same explicit marker as other fixtures.
The real drilldown acceptance covers omitted search, case-insensitive search, and
no-match search; optional search binds are explicitly typed for PostgreSQL.
CI jobs have bounded 30-minute budgets to accommodate full synthetic dbt builds
and real-browser setup on the shared runners.
The category picker and split editor retain existing archived assignments while
preventing new archived-category selections.

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
Signed feature-branch publication was explicitly authorized.
Merging, deploying, and live personal consent are not authorized.
Keep the epic and child issues open until their acceptance criteria are satisfied.
