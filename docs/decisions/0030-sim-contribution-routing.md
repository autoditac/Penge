# 0030 — ASK cap overflow contribution routing

- **Status:** Proposed
- **Date:** 2026-05-14
- **Deciders:** @autoditac
- **Tags:** sim

## Context and Problem Statement

Once a saver's Aktiesparekonto (ASK) cumulative deposit total reaches the SKAT
lifetime cap, any additional monthly savings must be redirected to a normal
brokerage account (*frie midler*). Prior to issue #137 there was no module in
`penge.sim` to compute this split automatically: callers had to derive the
residual ASK room themselves and hard-code the overflow amount.

We need a **thin, pure-function layer** that accepts the router configuration
(cap, running deposit total, monthly contribution) and returns the correct DKK
split for any projected year or month, ready to be fed into separate
`LiquidDepotConfig` instances for independent tax-aware projections.

## Decision Drivers

- Results must be deterministic and numerically reproducible from a small,
  user-controlled parameter set.
- The module must compose with the existing `penge.sim.liquid.project_liquid`
  API: each yearly split feeds directly into `annual_contribution_dkk` of a
  `LiquidDepotConfig`.
- The cap figure changes annually (SKAT adjusts the limit); the router must
  accept it as an explicit input rather than look it up internally, so callers
  can supply the confirmed SKAT figure or use
  `penge.sim.liquid.ask_cap_for_year` as they see fit.
- The computation should be stateless so it is easy to test in isolation and
  safe to call from parallel scenarios without shared mutable state.

## Considered Options

1. **Stateless replay** — `route_contributions(router, year)` recomputes the
   cumulative total from scratch by replaying years 1 … year-1 on every call.
   A separate `simulate_routing(router, n_years)` does a single O(n) forward
   pass for bulk projections.
2. **Stateful integrator** — a mutable object that accumulates deposits
   year-by-year as `next_year()` is called; caller must manage lifetime.
3. **Inline derivation in `LiquidDepotConfig`** — encode the overflow logic
   directly inside `project_liquid`, surfacing overflow as
   `contribution_overflow_dkk` on each `YearlyLiquidFlow` (already present in
   that model) so the caller can re-route it.

## Decision

We chose **Option 1 (stateless replay + single-pass simulator)**, because:

- A frozen Pydantic model (`ContributionRouter`) for configuration eliminates
  accidental mutation between calls; the "replay" function is trivially correct
  and requires no teardown.
- `simulate_routing` (O(n) single pass) covers the common bulk-projection case
  without the correctness risk of a stateful integrator that can be called in
  the wrong order.
- Keeping the routing logic outside `project_liquid` preserves the separation
  between *how much to contribute* (routing) and *how the depot grows* (liquid
  simulation). Callers compose the two independently, which aligns with the
  existing design of `penge.sim.cashflow` → `penge.sim.montecarlo`.
- Monthly granularity (`simulate_routing_monthly`) is a natural extension of
  the same stateless pattern, exposing the exact month the cap is hit without
  any architectural coupling to the yearly projection path.

## Consequences

### Positive

- Pure functions are trivially testable and composable.
- Each `YearlyContributionSplit.ask_contribution_dkk` feeds directly into
  `LiquidDepotConfig.annual_contribution_dkk` with no adaptation layer.
- Monthly and yearly granularities are independent; neither depends on the
  other internally.

### Negative

- `route_contributions(router, year)` is O(year): callers querying a single
  far-future year pay a cost proportional to that year index. For typical FIRE
  horizons (≤ 50 years) this is negligible; for unit tests it is invisible.
- The constant cap assumption (one `ask_cap_dkk` for the entire horizon)
  slightly overstates ASK room in years where SKAT raises the cap mid-horizon.
  Callers can work around this by re-constructing a new `ContributionRouter`
  for each segment once a new cap figure is published.

### Neutral

- The existing `project_liquid` overflow signal (`contribution_overflow_dkk`
  on `YearlyLiquidFlow`) remains available for callers who prefer to drive
  overflow detection from the liquid projection rather than the router.

## Alternatives in detail

### Option 2 — Stateful integrator

A class with `deposit_year()` → `(ask, frie)` mutation avoids the O(year)
replay cost, but forces callers to manage instance lifetime, makes
multi-scenario parallelism non-trivial (shared state), and complicates testing
(each test must construct a fresh instance). The performance benefit is
irrelevant at FIRE-modeling scale.

### Option 3 — Inline overflow in `project_liquid`

`project_liquid` already surfaces `contribution_overflow_dkk` on each
`YearlyLiquidFlow`. Extending it to automatically route overflow to a second
depot would create tight coupling between two otherwise independent accounts,
require passing a second `LiquidDepotConfig` into `project_liquid`, and
complicate the function signature. Keeping routing separate maintains the
single-responsibility boundary.

## Links

- Implements issue #137 (ASK contribution routing)
- Depends on ADR-0022 (`penge.tax.aktiesparekonto`, issue #134) and
  ADR-0026 (`penge.sim.liquid`, issues #135/#138)
- `src/penge/sim/routing.py`
- `tests/sim/test_routing.py`
