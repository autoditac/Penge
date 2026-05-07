# 0007 — Initial relational data model

- **Status:** Accepted
- **Date:** 2026-05-07
- **Deciders:** @autoditac
- **Tags:** infra, data-model

## Context and Problem Statement

Phase 0 must lock in a schema for the operational store before any
ingestion connector lands. Connectors (PSD2, Nordnet CSV, ECB FX),
the dbt analytics layer, the Streamlit dashboard, and the tax
modules all depend on a stable shape for accounts, transactions,
holdings, prices, FX, documents, and tax lots. Designing this once,
explicitly, avoids per-connector schema drift and ad-hoc migrations.

## Decision Drivers

- ADR-0001 commits us to Postgres 17 as the source of truth.
- The migrations.instructions.md file mandates `Numeric(20, 4)` for
  money, timezone-aware timestamps, named FKs/indexes, and a working
  `downgrade()` for every `upgrade()`.
- We need to support fractional crypto and high-precision FX, so a
  single money type isn't sufficient.
- Multi-currency reporting (ADR-0004) requires FX rates as first-class
  data with effective dates, not on-the-fly conversion.
- Tax-lot tracking (FIFO / DK Lagerbeskatning, see #36) requires a
  durable per-lot table linked to opening and closing transactions.

## Decision

The initial migration (`migrations/versions/0001_initial_schema.py`)
creates nine tables:

| Table | Purpose |
|---|---|
| `entity` | Owner of accounts and documents (person, household). |
| `account` | Bank, broker, pension, or crypto account. |
| `instrument` | Tradable asset (equity, ETF, bond, fund, crypto). |
| `transaction` | Ledger entry on an account; the canonical event. |
| `holding_snapshot` | Point-in-time portfolio holding per account. |
| `price_history` | Daily close per instrument. |
| `fx_rate` | Per-day base/quote exchange rates (ECB-style). |
| `document` | Statements, tax forms, salary slips, invoices. |
| `tax_lot` | Per-lot accounting tying open and close transactions. |

Type conventions:

- **Money** is `Numeric(20, 4)` (≥ 16 integer digits, 4 decimal
  digits — covers EUR/DKK/USD across realistic personal-finance
  ranges with sub-cent precision).
- **Quantities** are `Numeric(28, 8)` (covers 8-decimal crypto and
  fractional ETF shares).
- **FX rates** are `Numeric(20, 8)` (ECB publishes 4–5 decimals; we
  reserve headroom).
- **Timestamps** are `TIMESTAMP WITH TIME ZONE` storing UTC.
- **Surrogate keys** are UUIDs generated server-side via
  `pgcrypto`'s `gen_random_uuid()`.

Naming conventions per migrations.instructions.md:

- Foreign keys: `fk_<table>__<column>`.
- Unique constraints: `ux_<table>__<columns>`.
- Indexes: `ix_<table>__<columns>`.

## Consequences

### Positive

- Connectors land against a frozen target — no "design first, refactor
  later" churn.
- Tax modules (DK and DE) have a real `tax_lot` table from day one;
  they don't have to reinvent lot accounting.
- The dbt layer can stage from these tables knowing the column types
  are stable.
- `Numeric(20, 4)` choice removes any future "what's the canonical
  money type" debate.

### Negative

- Future schema changes are real migrations with `downgrade()` —
  small velocity tax.
- We commit to UUIDs rather than serial IDs; UUID indexes are larger
  and slightly slower (acceptable at single-user scale).

### Neutral

- `raw jsonb` on `transaction` keeps the original PSD2 / CSV payload
  alongside the parsed fields. Useful for debugging and for re-parsing
  after parser fixes; ignored by analytics.

## Alternatives in detail

### One wide `account_event` table instead of `transaction` + `holding_snapshot`

Rejected: holdings are derivative state (point-in-time aggregate of
all prior transactions), but provider feeds (Nordnet, GoCardless)
publish them directly. Storing both lets us reconcile derived vs
reported holdings; collapsing them loses that reconciliation signal.

### Separate per-asset-class tables (`equity`, `bond`, `crypto`, …)

Rejected: every analytical query would `UNION` four tables. The
ergonomic and dbt-friendly choice is one `instrument` table with a
`kind` discriminator.

### Generated identity columns (`bigint identity`) instead of UUIDs

Rejected: UUIDs let us generate IDs client-side in connectors before
inserting (useful for idempotency and bulk loading) and avoid leaking
volume information through monotonically-increasing IDs.

## Links

- ADR-0001 (self-hosted Postgres + DuckDB stack)
- ADR-0004 (EUR and DKK shown in parallel)
- `.github/instructions/migrations.instructions.md`
- `migrations/versions/0001_initial_schema.py`
