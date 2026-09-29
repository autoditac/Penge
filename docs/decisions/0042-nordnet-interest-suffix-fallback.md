# 0042 — Nordnet interest types: `…RENTE` suffix fallback to `cash_interest`

- **Status:** Accepted
- **Date:** 2026-06-16
- **Deciders:** @autoditac
- **Tags:** ingest

## Context and Problem Statement

The Nordnet transaction parser maps each `Transaktionstype` to a
canonical `kind` via an explicit table (`NORDNET_TXN_TYPE_MAP`).
Any value not in the table raises `ValueError`, which aborts the
**entire** CSV import — one unknown row blocks every other row.

Nordnet emits a growing family of interest types, all sharing the
Danish suffix `RENTE`: `KREDITRENTE` (credit interest),
`OVERBELÅNINGSRENTE` (margin/over-collateralization loan interest,
issue #244), `DEPOTRENTE` (custody-account interest, issue #246),
and likely others we have not seen yet. Each new label has so far
broken an import and required a one-line code change plus a deploy.
This is a whack-a-mole loop with poor user experience: the failure
is opaque, blocks the whole upload, and needs an engineer.

All of these are economically the same thing — interest on cash —
and all map to the existing canonical kind `cash_interest`, with
the sign of the amount carrying the income (credit) vs expense
(debit) direction. They land in the same returns attribution class
and the same DK `kapitalindkomst` tax bucket. There is no
tax-treatment difference between them that the canonical model
distinguishes today.

## Decision Drivers

- A new interest label must not abort an otherwise-valid import.
- Interest is unambiguously `cash_interest`; the sign already
  encodes direction. No new vocabulary is warranted.
- Keep well-known types explicit and testable for readability.
- Avoid silent misclassification of genuinely unknown,
  non-interest transaction types.

## Considered Options

1. **Explicit-only mapping** — keep adding each `…RENTE` value to
   `NORDNET_TXN_TYPE_MAP` as it appears.
2. **Suffix fallback** — keep the explicit table for known types,
   but if an unmapped type ends in `RENTE`, classify it as
   `cash_interest` instead of raising.
3. **Drop the unknown-type guard entirely** — default every
   unmapped type to something generic.

## Decision

We chose **Option 2 (suffix fallback)**. `_resolve_canonical_kind`
still consults the explicit table first (so known types stay
documented and unit-tested), still special-cases
`INDSÆTTELSE`/`HÆVNING`, and only then, before raising, returns
`cash_interest` for any `nordnet_type.endswith("RENTE")`. Genuinely
unknown, non-interest types still raise `ValueError` as before.

The well-known interest types (`KREDITRENTE`, `DEPOTRENTE`,
`OVERBELÅNINGSRENTE`) remain explicit entries in
`NORDNET_TXN_TYPE_MAP` for clarity and regression coverage; the
fallback is the safety net for ones we have not catalogued.

## Consequences

### Positive

- A previously-unseen Danish interest label no longer breaks an
  import; it is classified correctly without a code change.
- The sign-carries-direction rule keeps debit and credit interest
  in one bucket with correct returns and tax treatment.
- Known types stay explicit and unit-tested.

### Negative

- A hypothetical non-interest Nordnet type that happens to end in
  `RENTE` would be silently classified as `cash_interest`. We judge
  this risk negligible: in Danish financial vocabulary the `RENTE`
  suffix denotes interest, and the canonical model has no finer
  interest sub-classification to lose.

### Neutral

- No change to the canonical `kind` vocabulary, dbt staging
  schema, marts, or tax modules — `cash_interest` already exists
  and is consumed everywhere.

## Links

- Code: `src/penge/ingest/nordnet/parser.py` (`_resolve_canonical_kind`),
  `src/penge/ingest/nordnet/constants.py` (`NORDNET_TXN_TYPE_MAP`)
- Docs: `docs/connectors/nordnet.md` (transaction-kind mapping table)
- Issues: #244 (`OVERBELÅNINGSRENTE`), #246 (`DEPOTRENTE`)
- Related: [ADR-0008](0008-nordnet-account-modelling.md) (kind vocabulary)
