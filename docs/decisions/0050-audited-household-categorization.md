# 0050 — Audited household categorization independent of source facts

- **Status:** Proposed
- **Date:** 2026-10-03
- **Deciders:** @autoditac
- **Tags:** data, ingest, web, security

## Context and Problem Statement

Household income/expense development needs editable categories, corrections, splits and reusable merchant defaults.
Imported bank facts and existing cashflow, investment, tax and net-worth calculations must remain unchanged.
The staged mappings in [ADR-0038](0038-import-mapping-suggestions-via-mcp.md) are suggestions beside an upload, not classifications of committed transactions.
PayPal purchase details correspond to checking-account movements and must not establish a second expense ledger.

## Decision Drivers

- Stable identity, exact Decimal conservation, explicit errors and traceable human decisions.
- Preserve manual corrections through repeat imports and concurrent edits.
- Conservative local learning without transaction exports, ML or external AI.
- Keep original bank amounts, dates and currencies authoritative.

## Considered Options

1. **Separate audited classification tables** with stable UUIDs, exact allocations and explicit reconciliation.
2. **Rewrite raw transaction fields** after categorization, losing source fidelity.
3. **Adopt an external personal-finance ledger**, introducing another reporting source of truth.

## Decision

Choose **separate audited tables** under the native Postgres/FastAPI architecture.
`household_category` stores income/expense trees with immutable financial type, revision, order and archive state.
Renames, reparenting and archive preserve all assignments; cycles and cross-type parentage are rejected.
Transfers and unclassified are treatment/review states, never category nodes.

`household_merchant` and provider-scoped exact `household_merchant_alias` retain household-confirmed identity separately from future public reference provenance.
Public references cannot automatically overwrite local identity, aliases or rules.
The public reference download/cache worker and its own storage are deferred to #332.
`household_rule` is append-only versioned deterministic evidence, not probabilistic inference.
Only a confirmed stable identity with consistent single-category human evidence can establish an active default.
Processor-only labels, marketplaces, unknown/mixed identities, splits, refunds and conflicting corrections cannot establish a blanket category.
Disabled versions require explicit re-evaluation; historical evidence is retained, so conflicts cannot be erased by overwriting the latest correction.

`household_classification` retains effective treatment, manual/rule provenance, rule version, edit revision and a source snapshot.
`household_allocation` contains signed original-bank-currency category amounts.
Expense debits are negative; refund credits are positive allocations to expense categories on the refund's own date.
Allocations must sum exactly to the bank amount using EUR/DKK cents.
Transfer/excluded/unclassified treatments have no category allocations.
`household_transaction_link` stores explicit transfer/refund references without modifying their source records.
Each correction, allocation replacement, reconciliation, rule change and audit event commits in one transaction.
Postgres enforces foreign keys/unique keys and append-only audit/rule history.
Optimistic revisions and a transaction advisory lock serialize household writes.

`household_payment_detail` is a separate **non-ledger** provider store.
Its unique key is `(provider, source_account_id, external_id)` with a verified stable non-PII account identity and immutable provider entry reference.
Original gross amount/currency/date and minimal whitelisted source metadata exist only for matching and enrichment.
The store never creates a canonical account, transaction or holding snapshot.
`household_payment_detail_link` references an authoritative bank classification and source detail revision.
Its signed **bank-currency** allocations must exactly reconcile to that bank movement; foreign gross amounts are never substituted.
Unmatched/ambiguous PayPal details stay review-only and contribute no standalone expense or wallet balance.
Grouped, delayed and foreign-currency detail associations remain explicit approvals, not heuristic automatic matches.

Bank sync applies active defaults only to newly inserted movements.
Existing movements remain unchanged until a persisted preview is explicitly approved.
Preview/apply checks source amount/currency/date/identity, alias version, current rule version and classification revision, and excludes manual overrides and existing reconciliation.
Source resync changes preserve manual categories/splits but flag `needs_review`, increment the edit revision and disable related defaults pending reconfirmation.
Consumers must compare the stored source snapshot and approved detail revisions; stale splits are not valid reporting facts.

The `/household` API is opt-in with `PENGE_HOUSEHOLD_ENABLED=true`.
It inherits the existing local-only/authenticated reverse-proxy boundary, not an Enable Banking credential gate.
Writes reuse the import engine and [ADR-0046](0046-scheduled-enable-banking-net-worth-refresh.md) refresh lock/pending marker.
Household reads use current canonical data immediately; refresh produces later classification-aware marts without altering existing marts.

## Consequences

### Positive

- Re-sync cannot erase corrections or silently promote stale allocations.
- No new dependency, FX convention or external transaction-data path.
- Downstream reporting/UI/provider work has reusable typed contracts.

### Negative

- Conservative identity learning leaves ambiguous transactions for human review.
- EUR/DKK bank cents are supported initially; other bank currencies require an explicit precision contract.
- Historical conflicts and split evidence require review rather than automatic rule activation.
- Dataset refresh, household marts/UI, PayPal adapter and envelope budgeting are separate changes.

## Links

- [Household API and integration contract](../api/household.md)
- [Original relational model](0007-initial-relational-data-model.md)
- [Sanctioned MCP data path](0005-llm-access-via-mcp-only.md)
- Issues #330 and #329.
