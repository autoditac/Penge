# 0027 — Liquid depot simulation model (ASK + frie midler, Lager/Realisation)

- **Status:** Proposed
- **Date:** 2026-05-13
- **Deciders:** @autoditac
- **Tags:** sim, tax

## Context and Problem Statement

We need to project the year-by-year evolution of liquid (taxable) investment
accounts for a DK household, then translate the end-state into a sustainable
monthly bridge withdrawal during the gap years between FIRE and folkepension.
A trustworthy projection has to model **three distinct tax regimes** —
Aktiesparekonto (ASK), frie midler under Lagerbeskatning, and frie midler
under Realisationsbeskatning — and the routing rules between them (ASK
cap, then frie midler overflow).

An earlier external model (Gemini sketch) used a single flat effective
net-of-tax rate, which materially under-states bridge sustainability for
ASK (cheaper 17 % tax) and over-states it for large frie-midler positions
that quickly exhaust the progressive bracket. We want every modelling
assumption to be explicit, year-aware, and unit-testable.

## Decision Drivers

- **Correctness over closed-form convenience.** A wrong PMT during the
  bridge years would have real, irreversible portfolio consequences.
- **Progressive aktieindkomst bracket is per-year, per-person.** Tax must
  be tracked on an annual basis (both for the mark-to-market lager flow
  and for realisation withdrawals during the bridge).
- **Year-indexed satser.** SKAT publishes new aktieindkomst thresholds and
  ASK caps every year — the model must surface uncertainty for years that
  fall outside the confirmed table.
- **Reproducibility.** All monetary inputs and outputs are `Decimal`.
  Float arithmetic is permitted only for the one-time conversion of the
  annual net rate to a monthly rate (`(1 + r)^(1/12) - 1`) inside
  `compute_bridge_pmt` and in the FIRE-comparison return projection in
  `compare_liquid_strategies`, where Decimal lacks a fractional `pow`.
  The float result is immediately re-quantised back to `Decimal`; all
  downstream accounting (balances, taxes, withdrawals) stays in
  `Decimal`.

## Considered Options

1. **Closed-form PMT with a flat effective net rate** (Gemini baseline).
2. **Monthly simulation + binary search PMT** (chosen).
3. **Annual-step simulation with a sub-annual interpolation** for the
   bridge phase.

## Decision

We chose **Option 2 — monthly simulation + binary search PMT** with the
following modelling invariants:

- One projection step per **year** in accumulation
  (`project_liquid` → `YearlyLiquidFlow`), one per **month** in the bridge
  (`compute_bridge_pmt` → `MonthlyBridgeFlow`).
- **ASK**: flat 17 % Lager (`penge.tax.aktiesparekonto.ASK_RATE`); annual
  contributions are capped at the cumulative ASK deposit limit returned
  by `ask_cap_for_year()` (which reads the internal
  `_ASK_DEPOSIT_CAPS_EXTENDED` table). Contributions above the cap are
  *not* moved into ASK; routing the overflow to a frie-midler depot is
  the caller's responsibility (`project_liquid` does not do it
  implicitly).
- **Frie midler Lager**: progressive 27 %/42 % on annual mark-to-market
  gain. The threshold used in the simulation is the per-config
  `LiquidDepotConfig.aktieindkomst_threshold_dkk` (held constant across
  the horizon — the caller chooses which year's value to seed it with);
  `AKTIEINDKOMST_THRESHOLDS` / `threshold_for_year()` are exposed for
  callers that need the per-year value.
- **Frie midler Realisation**: dividends taxed at aktieindkomst rates in
  the year received; capital gain deferred. The bridge withdrawal computes
  the **gain fraction** from the current cost basis and taxes only that
  portion. Year-to-date realised gains drive the progressive bracket —
  later-year withdrawals correctly spill into 42 %.
- **`threshold_for_year` and `ask_cap_for_year`** both fall back to the
  latest known value for *future* years (conservative — assumes no further
  indexation) and **raise `LiquidDepotError`** for years *before* the
  earliest configured year (no silent back-projection).
- **All Decimal inputs are validated via the shared sim helper
  `penge.sim._decimal_utils.to_decimal`** (imported as `_to_decimal` in
  both `cashflow.py` and `liquid.py`), which rejects `NaN`/`Infinity`
  and raises a clear `ValueError`.
- **Bridge PMT search** validates `annual_net_rate > -1` up front; grows
  the upper bracket in a loop until depletion is bracketed; aborts with a
  clear error if no positive PMT can deplete the depot within the horizon
  or if the chosen PMT depletes mid-simulation.
- **`tax_due_dkk` is always the full liability**; only the depot-deducted
  portion changes with `tax_source` (`"external"` vs `"depot"`).

## Consequences

### Positive

- Numbers are reproducible, year-indexed, and unit-testable across the
  full ASK/Lager/Realisation matrix.
- Each tax regime's effect on bridge sustainability is **visible**
  (cf. the strategy-compare table in `compare_liquid_strategies`).
- Future SKAT updates only require touching `AKTIEINDKOMST_THRESHOLDS`
  and `_ASK_DEPOSIT_CAPS_EXTENDED` — no model code changes.

### Negative

- Monthly simulation + binary search is ~60× slower than a closed-form
  PMT. For 60 iterations × 120 months that's ≈ 7 200 monthly steps per
  call — still sub-millisecond in practice but materially slower than a
  scalar formula.
- The model holds the aktieindkomst threshold constant during the bridge
  (no per-year inflation indexation during the multi-year horizon).
  Acceptable for now; tracked as a follow-up if the bracket-creep over
  10 years becomes material.

#### Known limitations

- **No loss carry-forward.** `compute_aktieindkomst_tax` returns zero
  for negative gains and does not track losses across years.  Real
  Aktieindkomst (frie midler) allows indefinite carry-forward of
  capital losses against future gains; ASK nets gains against losses
  via the all-time deposit basis at withdrawal.  Projections that
  cross a drawdown followed by a recovery will therefore overstate
  tax in the recovery year(s).  Callers that need fidelity in loss
  scenarios must implement carry-forward state on top of this
  primitive.  Tracked as a follow-up; current users (FIRE
  modelling at ≥ 10 y horizon) work with expected paths and accept
  the bias.
- **Dividend yield is interpreted as net of ÅOP.**  Internally the
  realisation split subtracts `opening_balance × annual_dividend_yield`
  from the **post-ÅOP** `gross_return` to derive capital appreciation.
  Suppliying a *gross* dividend yield would overstate taxable
  dividends.  Use factsheet yields that already net out ÅOP, or
  pre-adjust before passing.

### Neutral

- Net rate is computed from `gross_return_rate − annual_expense_ratio`;
  ÅOP is therefore symmetric (compounds against accumulating funds and
  separate from dividend yield for distributing funds).

## Links

- Code: `src/penge/sim/liquid.py`
- Tests: `tests/sim/test_liquid.py`
- Tax helpers: `penge.tax.aktiesparekonto`, `penge.tax.lager`
- Related issues: #134 (ASK), #135 (Lager vs Realisation), #136 (ÅOP),
  #137 (routing), #138 (fund compare), #139 (bridge decumulation),
  #142–#146 (review findings folded into this ADR)
- Domain: `docs/tax/dk.md`
