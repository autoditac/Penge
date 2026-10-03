# 0049 — Account-scoped Nordnet holdings-only imports

- **Status:** Proposed
- **Date:** 2026-10-01
- **Deciders:** @autoditac
- **Tags:** api, ingest, security, data

## Context and Problem Statement

[ADR-0037](0037-staged-import-sessions.md) excluded Nordnet holdings-only
uploads because the loader mapped names from the same transaction export and
silently skipped unknown positions.
The staged Imports API needs to accept separately uploaded holdings exports.

## Decision Drivers

- Never silently omit a holding from an accepted snapshot.
- Never infer an ISIN from another account's history.
- Preserve transaction-derived cash balances and the CLI's combined-file path.
- Avoid unrelated account updates during a single-account import.

## Considered Options

1. **Resolve from account history at commit** — look up instrument names via
   existing trades and snapshots, with same-account transactions in the current
   load as additional evidence; reject missing or ambiguous mappings.
2. **Global name lookup** — can wrongly attribute a position to another account.
3. **Name-only instruments** — discards stable ISIN identity and complicates
   reconciliation when transactions arrive later.

## Decision

Choose **option 1**. A distinct `nordnet_holdings` staged source retains the
account and date from the Nordnet filename and validates account configuration.
Rows remain editable/excludable; commit revalidates them and calls the existing
loader with an empty transaction list.
The loader uses account-scoped transaction and holding history, then same-account
input transactions, to resolve every holding to an ISIN before writing.
Missing or conflicting mappings reject the entire database transaction.
Only accounts referenced by the load are upserted.
Cash continues to be derived solely from transactions.
Each Depotoversigt represents the complete security positions on one
account/date. The loader writes zero quantity and market value at that date
for previously active account securities missing from the file (including
those present in a prior import of the same date). It never synthesizes cash
zeros or changes another account. A same-date correction can restore a
position by upserting the included security over its zero row.
Duplicate account/date exports in one load are rejected.
A header-only export is a valid empty snapshot, whereas excluding all rows
from a nonempty staged export is rejected. Empty exports require the full
provider header and a validated account/date filename; the staged session
records an empty-export marker, and commit checks the stored file and SHA-256
again before permitting zero-all semantics. Commit also requires an existing
ISIN-mapped security snapshot for that Nordnet account on or before the
export date; a header-only file cannot create an unrelated or untracked
account. Failed loads remain staged and do not contribute to account freshness.
The account read API takes the latest committed staged Nordnet session with an
included row for that account into account freshness. Raw snapshot/transaction
creation timestamps remain the fallback for CLI and historical loads. A
repeat import can therefore advance `last_updated_at` without changing
`balance_changed_on`. No additional persistence or migration is required.

## Consequences

### Positive

- Individual future snapshots can be reviewed and imported without re-exporting
  history, and no position silently disappears.
- A repeated account/date import converges through the existing unique-key upsert.
- Sold positions no longer stay nonzero indefinitely in the forward-filled
  daily valuation mart.

### Negative

- A holding not yet present in the account's ingested history requires its trade
  export first; holdings-only import cannot invent a reliable ISIN.

### Neutral

- No schema changes or new dependencies are required.
- Existing CLI transaction-plus-holdings ingestion uses the same resolution path.

## Links

- [ADR-0008](0008-nordnet-account-modelling.md)
- [ADR-0037](0037-staged-import-sessions.md)
- [Nordnet connector](../connectors/nordnet.md)
- Issue #296 — Nordnet account freshness and holdings imports
