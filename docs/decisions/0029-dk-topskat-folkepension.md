# 0029 — DK Topskat and Folkepension Modules

- **Status:** Proposed
- **Date:** 2025-08-01
- **Deciders:** @autoditac
- **Tags:** tax, sim

## Context and Problem Statement

FIRE modeling for a DK household with a large pension balance (~18 M DKK) requires
understanding two DK-specific tax and benefit interactions at retirement:

1. **Topskat** (#129) — annual pension income from Livrente + Ratepension will far exceed
   the 588 900 DKK threshold (2026), triggering the 15 % surtax. Without visibility into
   this, the scenario engine overstates net income.

2. **Folkepension modregning** (#131) — the means-tested pensionstillæg (up to ~18 389 DKK/
   month single, ~8 993 DKK/month married) is reduced by 30.9 % of private pension income
   above 94 800 DKK/year. At ~900 000 DKK/year the tillæg is zeroed entirely. Planning
   should reflect that only the universal grundbeløb (~7 191 DKK/month) will be received.

Both modules are pure computation aids: they take a projected annual income and return a
structured result. They do not touch persistence, I/O, or the main cashflow simulation.

## Decision Drivers

- Correctness: the existing `sim/tax.py` and `sim/payout.py` cover cashflow and generic tax
  but have no DK-specific Topskat or folkepension logic.
- Locality: DK-specific rules belong in a `penge/tax/dk/` subpackage, separate from DE rules
  and from the generic simulation engine.
- Annual update cycle: rate constants change each January; a single `rates.py` file makes
  the update surface explicit and reviewable.
- Integration: `PayoutProjection` (from ADR-0028) is the natural input; both modules provide
  `*_from_payout()` helpers that accept a `PayoutProjection` and an EUR/DKK rate.

## Considered Options

1. **New `penge/tax/dk/` subpackage** — `rates.py`, `topskat.py`, `folkepension.py`
2. **Inline into `sim/tax.py`** — extend the existing generic tax module
3. **Inline into `sim/payout.py`** — add DK-specific post-processing to the payout module

## Decision

We chose **Option 1** (new subpackage), because:

- DK-specific logic must not pollute the country-neutral `sim/` layer.
- A dedicated subpackage (`tax/dk/`) mirrors the existing `tax/de/` trajectory and is
  trivially extensible to additional DK rules (e.g., aktiesparekonto, kapitalindkomst).
- `rates.py` as a single update target satisfies the annual-review requirement.

## Consequences

### Positive

- Topskat and folkepension checks are accessible to the scenario engine, the MCP server
  (`compute_tax_year` tool, issue #49), and future dashboard widgets.
- `PayoutProjection.total_monthly_gross_eur` + an EUR/DKK rate is the only coupling point;
  the rest of the modules are fully self-contained and independently testable.
- Pure functions + frozen dataclasses → trivially serialisable, no hidden state.

### Negative

- EUR/DKK conversion is the caller's responsibility; if the FX rate is stale the output
  will be wrong. The docstrings document this clearly.
- Rate constants are approximate (sourced from SKAT/Ankestyrelsen press releases, not
  official ministerial orders); they must be verified each January.

### Neutral

- The modules do not apply personfradrag or AM-bidrag; callers who need gross-to-net accuracy
  must subtract those before calling. This is documented in the module docstrings.

## Module summary

| File | Exports |
|------|---------|
| `penge/tax/dk/rates.py` | `DK_TOPSKAT_RATE`, `DK_TOPSKAT_THRESHOLD_DKK`, `FOLKEPENSION_*` constants, `FOLKEPENSION_AGE_SCHEDULE` |
| `penge/tax/dk/topskat.py` | `TopskatWarning`, `check_topskat_exposure()`, `topskat_from_payout()` |
| `penge/tax/dk/folkepension.py` | `FolkepensionConfig`, `FolkepensionResult`, `compute_folkepension()`, `folkepension_from_payout()`, `folkepension_age_for_year()` |

## Links

- Issue #129 — Topskat exposure warning
- Issue #131 — Folkepension modregning model
- ADR-0028 — Payout modeling (`PayoutProjection` as input type)
- `src/penge/tax/dk/`
- `tests/tax/dk/`
