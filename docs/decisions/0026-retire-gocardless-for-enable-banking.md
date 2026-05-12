# 0026 — Retire GoCardless Bank Account Data; standardize on Enable Banking

- **Status:** Proposed
- **Date:** 2026-05-12
- **Deciders:** @autoditac
- **Tags:** ingest, security
- **Supersedes:** [ADR-0003](0003-hybrid-ingestion-psd2-and-csv-pdf.md)

## Context and Problem Statement

[ADR-0003](0003-hybrid-ingestion-psd2-and-csv-pdf.md) selected GoCardless
Bank Account Data (formerly Nordigen) as Penge's PSD2 gateway for the
DK/DE retail-banking sources (GLS, Evangelische Bank, Lunar). Since then
two things changed:

1. **GoCardless paused new Bank Account Data signups** in early 2026,
   creating a hard onboarding wall for any future bank Penge wants to
   add.
2. **Penge migrated all three live PSD2 connectors** (issues #14 GLS,
   #15 Evangelische Bank, #16 Lunar) to **Enable Banking** in PRs
   [#82](https://github.com/autoditac/Penge/pull/82) and
   [#83](https://github.com/autoditac/Penge/pull/83). The transport client
   lives in `src/penge/ingest/enablebanking/` and the GLS/Ebank/Lunar
   packages now wrap it via a shared mapping layer.

That leaves `src/penge/ingest/gocardless/` as dead code: it is imported
by nothing, no live connector targets it, no CI job exercises it.

## Decision Drivers

- **Operational reality:** the only PSD2 path that actually runs against
  our three banks today is Enable Banking. We should not maintain a
  parallel transport that is exercised solely by its own unit tests.
- **Security surface:** unused credentials + dormant HTTP clients are
  liability, not optionality. Fewer secrets to rotate is strictly better.
- **Doc-code drift:** keeping the GoCardless connector page in the
  user-facing docs implies it is a supported onboarding path; it is not.
- **Reversibility:** GoCardless's Bank Account Data product still exists
  for grandfathered customers, and the deleted client is preserved in
  git history. If we ever need it back, `git revert` plus a fresh
  `secret_id` / `secret_key` is enough.

## Considered Options

1. **Delete the GoCardless module, tests, and docs; standardize on Enable
   Banking for PSD2.**
2. **Keep the module as a maintained second option,** in case Enable
   Banking changes terms.
3. **Soft-deprecate only** (leave the deprecation banner in the
   `__init__.py` docstring as today) but ship no new feature work.

## Decision

We chose **Option 1**.

- Removed:
  - `src/penge/ingest/gocardless/` (the entire transport client +
    Pydantic models)
  - `tests/ingest/test_gocardless.py`
  - `docs/connectors/gocardless.md` (and its nav entry)
  - `GOCARDLESS_SECRET_ID` / `GOCARDLESS_SECRET_KEY` placeholders in
    `.env.example`
- Updated `AGENTS.md`, `SECURITY.md`, `docs/connectors/index.md`, and
  the ADR index to refer to Enable Banking instead of GoCardless.
- ADR-0003 is marked **Superseded** by this ADR; its rationale (hybrid
  PSD2 + CSV/PDF parsers) stands, only the PSD2 vendor changes.
- Historical ADRs that mention GoCardless as factual context
  ([ADR-0007](0007-initial-relational-data-model.md),
  [ADR-0008](0008-nordnet-account-modelling.md)) are left intact —
  rewriting them would falsify the historical record.

## Consequences

### Positive

- One PSD2 transport to maintain, test, and pin (`enablebanking` dep
  group).
- Smaller secret inventory and one fewer third-party portal to monitor
  for breach notifications.
- Onboarding instructions become unambiguous: every PSD2 connector
  page points at `penge.ingest.enablebanking`.

### Negative

- No drop-in fallback if Enable Banking changes terms or pricing. The
  mitigation is plain `git revert` of this change plus a fresh signup;
  the API shapes are stable enough that the deleted client would still
  work against today's GoCardless endpoints.
- Anyone with a fork running against grandfathered GoCardless
  credentials must either pin to the pre-revert SHA or migrate.

### Neutral

- Enable Banking, like GoCardless before it, requires periodic SCA
  re-authentication (every 90–180 days). The consent-expiry monitoring
  story is unchanged.

## Alternatives in detail

### Option 2 — keep as maintained second option

Rejected: it is not currently maintained — there are no live tests
against the real GoCardless sandbox, no CI mock-roundtrip, and no
connector that uses it. Calling it "maintained" would be aspirational.

### Option 3 — soft-deprecate only

Rejected: dormant code drifts. Every dependency bump, mypy ratchet,
and ruff rule change costs us churn against code that nobody runs.
The deprecation banner has been in place since the Enable Banking
migration landed; keeping it longer buys nothing.

## Links

- ADR-0003 (superseded)
- PR #82 — Evangelische Bank via Enable Banking
- PR #83 — Lunar via Enable Banking
- `src/penge/ingest/enablebanking/`
