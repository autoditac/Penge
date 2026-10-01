# 0047 — Per-account bank metadata corrections

- **Status:** Proposed
- **Date:** 2026-10-01
- **Deciders:** @autoditac
- **Tags:** ingest, web

## Context and Problem Statement

Enable Banking consents can cover several accounts belonging to different household members.
The provider does not reliably supply an account kind, so Penge defaults every cash account to `checking` and every account on a consent to its connection owner.
A correction made only to the `account` row is lost at the next sync, because the loader refreshes `entity_id`.
Account balances are unsuitable as identifiers: they change and can coincide.

## Decision Drivers

- Corrections must target stable internal account IDs without storing household-specific identifiers in the repository.
- A sync must not overwrite a correction, but uncorrected accounts must keep following the connection owner.
- Corrections must immediately affect the canonical account dimension and eventually the analytics marts.

## Considered Options

1. **Store per-account overrides alongside the canonical account** — nullable owner and kind override columns.
2. **Change connection ownership for the entire consent** — cannot express mixed-owner connections.
3. **One-off SQL updates** — overwritten by the next sync.

## Decision

We chose **per-account overrides on `account`**.
A guarded metadata PATCH writes both the effective account value and its override in one transaction.
The Enable Banking upsert uses the owner override when present, otherwise the connection owner.
An account without an override retains its existing kind; cash accounts start as `checking`.
A durable refresh intent is recorded when metadata changes so the next guarded analytics refresh rebuilds the marts.
No account IDs, names, or balances are committed to the repository.

## Consequences

### Positive

- Different accounts on the same consent can have different owners and kinds without relinking.
- Overrides survive scheduled and manual syncs and can be inspected alongside effective values.

### Negative

- Operators need to identify the account by the current balance in the authenticated UI, then use its stable account ID for the correction.
- Reversing the schema migration removes override persistence; operators should not downgrade a live deployment without first recording its overrides securely.

### Neutral

- Other ingestion providers and unaffected bank accounts keep their existing behavior.

## Links

- [Enable Banking consent](0040-in-app-enable-banking-consent-flow.md)
- [Account correction runbook](../runbook/account-metadata.md)
