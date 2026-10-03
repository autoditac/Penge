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
The runner selects the acceptance seed's explicit provider/external account
identity rather than assuming no other synthetic checking accounts exist.
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
Verbose pytest progress, the twenty slowest test durations, and wall/user/system
timing for the acceptance and dbt commands distinguish expensive builds from
stalled tests or shared-runner contention; a larger budget alone is not evidence.
Measured CI showed file-backed SQLite fixture setup taking up to 62 seconds per
test on the shared runner.
The default household unit/API fixture now uses isolated in-memory SQLite with
one shared connection for TestClient threads; real PostgreSQL gates are unchanged.
The category picker and split editor retain existing archived assignments while
preventing new archived-category selections.
Browser smoke fixes its client clock to the synthetic June fixture window and
accepts the dashboard's initial category fetch instead of requiring a redundant
request after cached navigation.
It still verifies a real category POST and a fresh persisted GET after reload.
Category response predicates require the API origin and JSON content type so a
same-path frontend document cannot be mistaken for persisted API data.
Each browser case has a bounded 90-second budget; failures retain synthetic
screenshots/traces for three days in CI.
Browser CI serves the production bundle with Vite preview rather than a mutable
development module graph; traces showed cold optimizer/network-changed failures.
The browser recipe builds that bundle explicitly before starting Playwright,
keeping compilation outside the server-readiness timeout and retaining the
real API origin and demo-disabled build flags.
Household writes commit in a function-scoped dependency before sending success
headers, preventing an immediate browser refetch from racing an uncommitted save.
An in-memory boundary regression checks commit-before-headers and commit failure
returning a conflict rather than a false success.
The shared write dependency is consumed only by household category, merchant and
alias create/update, rule control/preview/apply, classification save, and undo.
All retain service-owned flushes and the dependency-owned transaction, audit and
refresh-intent lock; exceptions unwind the transaction and release the lock.
Other API writers are unchanged.
Household read sessions explicitly disable mutation row locks: concurrent list,
detail and suggestion GETs previously locked distinct transactions then their
shared account in inconsistent order, producing a real PostgreSQL deadlock.
Write sessions retain their advisory lock, row locks and revision checks.
The read/write source-lock regression verifies both modes; browser persistence
reads remain concurrent and are not serialized to hide this defect.
Merchant selection scrolls the control into view before keyboard opening,
uses native Home/ArrowDown/Enter with a selected-label assertion, then reopens the
menu and verifies the option is fully in the viewport and pointer-selectable.
This covers both keyboard and mobile touch geometry without forced clicks.
Reopening waits for the previous listbox to unmount, so modal focus/scroll
restoration cannot race the next pointer action during the exit transition.
Touch projects use native taps rather than mouse down/up synthesis and assert
the combobox is expanded before testing the option's viewport geometry.
Versioned rule regions expose accessible names so history actions target the
active version explicitly instead of depending on layout ancestry.

### Connected browser coverage

Separate July device-scoped sources leave the June report and MCP goldens unchanged.
The seed uses household services to establish confirmed merchant/alias evidence,
an active learned rule, protected manual evidence, and an unclassified historical
candidate; public reference promotion uses a clearly synthetic two-record catalog
without downloading anything or claiming publisher verification.
Four review-only PayPal details are seeded without adding bank transactions.
An in-memory regression verifies isolated device candidates and zero initial links.
Browser bank entries retain unique stable synthetic external IDs, including the
provider staging not-null contract; the household read-only source projection
exposes the existing raw column without introducing a migration.

Desktop and mobile journeys exercise category-filtered real report drilldown,
keyboard bulk selection, persisted manual bulk assignments, rejected unbalanced
splits and exact balanced split persistence, local public reference search/linking,
alias creation, and an actual concurrent merchant revision producing a failed save.
History preview is checked for non-mutation before explicit approval, followed by
persisted rule assignment and unchanged protected manual evidence.
Manual correction and explicit aggregate PayPal reconciliation retain category
allocations and bank identities/amounts across reload; invalid conservation blocks
approval.
These are connected persistence checks, not replacements for component/API tests.
Component tests already cover archived choices, category hierarchy controls,
decimal precision, missing-FX presentation, preview review guards, and vendor states.
API/service tests cover source reimports, stale previews/details, deterministic
learning conflicts, audit/undo, and public generation failure/privacy behavior.

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
