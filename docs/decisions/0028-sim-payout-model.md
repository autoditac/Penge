# 0028 — Decumulation payout model: annuity factor + PMT

- **Status:** Proposed
- **Date:** 2026-05-12
- **Deciders:** @autoditac
- **Tags:** sim, tax

## Context and Problem Statement

Penge can model pension accumulation through `penge.sim.cashflow`, but cannot
yet answer the core retirement question: *"How much will I receive per month?"*
A Danish occupational pension (e.g. PFA) distributes its capital at retirement
across up to three products — Livrente (lifelong annuity), Ratepension
(fixed-term drawdown), and Aldersforsikring (lump sum) — each with different
cash-flow profiles and tax treatment.

We need a deterministic module that converts a projected pension balance into
gross monthly retirement income and a one-off lump sum, so that downstream
modules (Topskat warning #129, Folkepension modregning #131) have a concrete
income figure to work with.

## Decision Drivers

- Results must be deterministic and reproducible from a small set of
  user-controlled parameters.
- The annuity factor (omregningsfaktor) is published by PFA and
  Finanstilsynet annually; hardcoding a value would make the model stale and
  untestable. The factor must be a first-class input.
- Ratepension drawdowns are tax-deferred; the residual balance continues to
  earn a return during the payout period, so a flat-division formula would
  understate income. A PMT formula is the correct analytical tool.
- This module is explicitly a *planning tool*, not a contract quotation. We
  accept model simplifications (constant annuity factor, constant PMT) in
  exchange for closed-form tractability.

## Considered Options

1. **Annuity factor for Livrente + PMT for Ratepension** (chosen)
2. **Flat capital division (no return during drawdown)**
3. **Full actuarial mortality table for Livrente**

## Decision

We implement `penge.sim.payout` with:

- `PayoutConfig` — a frozen Pydantic model holding the entity's pension balance
  at retirement, allocation fractions, and two model parameters
  (`annuity_factor` and `growth_rate_during_payout`).
- `PayoutProjection` — computed capital splits and gross monthly amounts.
- `compute_payout(config) → PayoutProjection` — pure function, no I/O.

**Livrente** monthly amount:

```text
monthly_livrente = livrente_capital × annuity_factor / 1_000_000
```

The annuity factor is a pure ratio (monthly/capital). PFA publishes values in
DKK per 1 000 000 DKK, but the ratio is currency-neutral: using a DKK-factor
with an EUR balance yields the same numerical answer as converting both to DKK
first.

**Ratepension** monthly amount: standard present-value PMT over
`ratepension_years × 12` months at the monthly rate derived from
`growth_rate_during_payout`:

```text
r_monthly = (1 + annual_rate)^(1/12) − 1
PMT = capital × r_monthly / (1 − (1 + r_monthly)^(−n))
```

When `growth_rate_during_payout = 0` this degenerates to `capital / n`.

The `(1/12)` exponent is computed in `float` for the single intermediate step;
all other arithmetic uses `Decimal`. The precision loss (< 1 × 10⁻¹⁴ relative)
is negligible for a 10–30 year planning horizon.

**Aldersforsikring** is the residual:
`1 − livrente_fraction − ratepension_fraction` of the balance, paid as a
one-off tax-free lump sum.

**Integration with `CashflowProjection`**: `payout_at(year, config)` looks up
the accumulated pension balance for `config.entity` at `year`, overrides
`pension_balance_eur`, and delegates to `compute_payout`. The import is
deferred (`TYPE_CHECKING` guard + local import inside the method body) to avoid
a circular import.

## Consequences

### Positive

- Answers the core retirement income question in a single function call.
- Fully testable: all parameters are explicit, no I/O or date dependencies.
- The annuity factor is user-supplied, so it can be updated annually without
  a code change.
- Unblocks #129 (Topskat exposure) and #131 (Folkepension modregning), both
  of which require a gross monthly income figure.

### Negative

- The constant-PMT assumption for Ratepension ignores PAL-skat on growth
  inside the pension during the drawdown period. The error grows with the
  payout horizon and the `growth_rate_during_payout` assumption. For a 5 %
  gross rate, PAL-skat (15.3 %) reduces the net rate to ~4.23 %; using the
  gross rate overstates monthly income by ~2 % over 20 years. Acceptable for
  planning; note in user-facing documentation.
- The Livrente annuity factor does not vary by age within this model. Actual
  factors differ between e.g. age 67 and 72 (later start → higher monthly
  per kr of capital). The user must supply the correct age-specific factor.
- No mortality or survivor-benefit modelling (DB spouse pension, minimum
  guarantee period). These are contract details that vary by provider and
  policy.

### Neutral

- Tax overlay (A-skat, Topskat) for the monthly Livrente and Ratepension
  payments is out of scope for this module; see #129.
- The `growth_rate_during_payout` is a gross rate. Users should supply the
  expected net-of-fees return. PAL-skat during payout is noted above.

## Alternatives in detail

### Option 2 — Flat division

Simply compute `monthly = capital / (years × 12)` regardless of whether the
residual earns a return.  This understates income when `growth_rate > 0`
(common for Danish pension depots, which continue to be invested during
payout).  Rejected because the error is systematic and in the conservative
direction, which may distort FIRE planning decisions.

### Option 3 — Full actuarial mortality table

Use Finanstilsynet's published mortality tables (G82, G2020) and a discount
rate to derive the annuity factor endogenously.  This would reduce the user's
parameter burden (no need to input the annuity factor) but would tie the model
to a specific discount-rate assumption, require the mortality CSV to be
maintained in the repo, and add ~300 lines of actuarial code for marginal
planning-accuracy benefit.  The annuity factor already encodes the provider's
pricing; accepting it as an opaque input is both simpler and more flexible.

## Links

- Issue: #132
- `src/penge/sim/payout.py`
- `tests/sim/test_payout.py`
- `penge.sim.cashflow.CashflowProjection.payout_at()`
- ADR-0011 (cashflow engine)
- ADR-0027 (liquid depot simulation model — bridge PMT, related PMT approach)
