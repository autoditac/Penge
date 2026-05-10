# 0017 — Lagerbeskatning calculator (annual mark-to-market for ABIS funds)

- **Status:** Proposed
- **Date:** 2026-05-10
- **Deciders:** @autoditac
- **Tags:** tax, dk

## Context and Problem Statement

Funds on the SKAT ABIS list (Aktiebaserede Investeringsselskaber — most
Irish-domiciled, UCITS equity ETFs) are taxed annually on the change in
market value, regardless of whether positions were realised. This is
**lagerbeskatning** (mark-to-market). The tax base is *kapitalindkomst*,
banded at 27 % up to 61 900 DKK (2024) and 42 % above.

Phase 3 needs a deterministic, pure calculator that produces the per-ISIN,
per-year gain in DKK so the SKAT report generator (#39) can apply the
household-level progressive bands.

## Decision Drivers

- Correctness against SKAT formula (see §1A and §15 of
  *Aktieavancebeskatningsloven*).
- Reproducibility: same inputs must always yield the same DKK number.
- Auditability: each per-ISIN result must show start/end MV, sum of buys,
  sells and distributions used in the calculation.
- Currency safety: SKAT operates in DKK only — non-DKK inputs must fail
  loudly. FX conversion is the caller's responsibility (it depends on
  the trade date / year-end FX rate from SKAT-published tables).

## Decision

| Item | Choice |
|---|---|
| **Module** | `penge.tax.lager` |
| **Formula** | `gain = end_mv − start_mv − Σ buys + Σ sells + Σ distributions` |
| **Currency** | DKK only on every input and output; non-DKK raises `LagerError` |
| **Scope** | One calculator call ↔ one `(account_id, isin, tax_year)` triplet |
| **Bands** | Not applied here — household-level aggregation belongs to #39 |
| **State** | None — the calculator is a pure function |
| **Precision** | All outputs quantized to 0.01 DKK using ROUND_HALF_EVEN |

## Consequences

### Positive

- Trivial to test: 15 unit + 2 hypothesis property tests cover the formula.
- Composes cleanly with `penge.tax.lots` (`Money` reused) and with the future
  SKAT report generator (#39): aggregate `LagerResult.gain` per year, then
  apply 27 % / 42 % bands.
- No FX risk: callers must convert to DKK first using the correct year-end
  rate, so the calculator stays independent of FX-source ADRs.

### Negative

- Caller bears the FX-conversion burden. We may revisit this when the
  ingestion pipeline grows a DKK-conversion service.
- The calculator does not verify that the ISIN is actually on the ABIS
  list — that's a job for the orchestrator that decides which calculator
  (`lager` vs `lots`) to run per holding. The ABIS classification lives
  in `penge.tax.abis` (ADR-0009).

## Rejected Alternatives

- **Bake the 27/42 % bands into this calculator.** Rejected: bands apply to
  the *household total* of capital income across all ABIS holdings, both
  spouses, plus other kapitalindkomst (interest etc.). Doing per-ISIN
  banding would double-count.
- **Combine `lager` and `lots` into one module.** Rejected: realisation and
  mark-to-market are different tax mechanisms with different input shapes
  and audit trails. Keeping them separate makes the SKAT report easier to
  reason about per ISIN.

## References

- ADR-0009 — ABIS list ingestion
- ADR-0016 — Tax-lot tracker (gennemsnitsmetoden, for non-ABIS instruments)
- `docs/tax/dk.md` — Lagerbeskatning section
- SKAT — *Aktier og investeringsbeviser*
