# 0016 — Tax-lot tracker uses gennemsnitsmetoden (single aggregate per ISIN)

- **Status:** Proposed
- **Date:** 2026-05-10
- **Deciders:** @autoditac
- **Tags:** tax, dk

## Context and Problem Statement

Phase 3 needs an authoritative cost-basis ledger for *realisationsbeskattede*
instruments — non-ABIS funds and individual stocks held in a Danish depot.
Danish tax rules prescribe **gennemsnitsmetoden**: a single running average
cost per ISIN per depot (account). Sales realise gain at that average; the
average itself is unaffected by partial sales.

This is distinct from US-style FIFO/LIFO/specific-identification: there are
no separate "lots" by purchase date. The book per ``(account_id, isin)`` is
a single quantity + cost-basis pair that is mutated by buy / sell / split /
merger events.

## Decision Drivers

- Correctness against Danish law (skat.dk: *Aktieavancebeskatningslovens § 24-26*).
- Auditability: every realisation produces a record we can later sum into a
  SKAT report (#39).
- Determinism: feeding the same chronological event sequence must produce
  identical lots and gains. No floating-point arithmetic on currency.
- Currency safety: a single ``(account, isin)`` cannot mix EUR and DKK. The
  book never converts; FX is the caller's responsibility.

## Considered Options

1. **Single aggregate per ``(account, isin)``** — quantity and cost-basis are
   mutated in place; the lot's average cost is `cost / quantity`.
2. **Lot-list with FIFO consumption** — keep a list of dated lots and
   consume on sell. Allows specific-identification reports later.
3. **Replay-from-events on every read** — never store state; recompute
   from the event log on demand.

## Decision

We chose **Option 1**, because it is exactly what Danish law requires and
nothing more: gennemsnitsmetoden does not let the taxpayer pick which lot
to dispose of. Encoding FIFO would add complexity that we would then have
to actively *suppress* on every realisation. Option 3 is too slow for
interactive use and would still require a snapshot type for reports.

The book is mutable internally; reads return frozen Pydantic snapshots
(`TaxLot`, `RealisedGain`). The realisation log is append-only.

## Consequences

### Positive

- Module is small (~300 lines) with a single source of truth per pair.
- Tests cross-validate against a hand-calculated example and 80
  hypothesis-generated trade sequences.
- Splits and mergers preserve cost basis exactly; only quantity changes.

### Negative

- We cannot retroactively switch to FIFO without replaying the event log
  through a different reducer. (Acceptable: DK tax law forbids the switch.)
- Mixing currencies on the same pair is rejected, not auto-converted.
  Callers that need FX must convert at the event level.

### Neutral

- The book is in-memory only. Persistence (Postgres backing) is out of
  scope for #35; #39 will materialise the realised-gains stream into a
  mart for reporting.

## Alternatives in detail

### Option 2 — Lot-list with FIFO

Useful for jurisdictions that allow specific-identification (US). Adds an
ordering decision on every sell that DK law does not give us.

### Option 3 — Replay on read

Pure-functional, audit-friendly, but every aggregation read becomes O(N)
in event count. The mutable book is itself a deterministic reducer over
the event stream, so determinism is preserved without the cost.

## Links

- Issue: [#35](https://github.com/autoditac/Penge/issues/35)
- Code: `src/penge/tax/lots.py`, `tests/tax/test_lots.py`
- Domain: [docs/tax/dk.md](../tax/dk.md) ("Realisationsbeskatning")
- Related ADRs: [ADR-0009](0009-abis-list-and-instrument-tax-treatment.md)
  (ABIS list determines whether gennemsnitsmetoden applies at all).
