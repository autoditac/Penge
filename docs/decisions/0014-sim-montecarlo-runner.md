# ADR-0014 — Vectorized Monte-Carlo FIRE Runner

| Field       | Value                                              |
|-------------|----------------------------------------------------|
| **Status**  | Accepted                                           |
| **Date**    | 2025-07-03                                         |
| **Issue**   | #31                                                |
| **Depends** | ADR-0010 (returns), ADR-0011 (cashflow), ADR-0012 (goal), ADR-0013 (tax) |

## Context and Problem Statement

The deterministic cashflow projection (#27) and goal evaluator (#30) use a
single income/portfolio path. To estimate the **probability** the household
reaches FIRE, and to obtain confidence intervals on the FIRE year and
portfolio trajectory, we need to run many stochastic paths and aggregate
results.

The acceptance criteria are:

- N=10 000 paths over 10 years in < 30 s on a laptop.
- Seeded: same inputs → identical outputs (bit-for-bit reproducible).
- Output includes 10/50/90 percentile paths and P(goal\_met).

## Decision

Implement `penge.sim.montecarlo.run()` that:

1. Applies the tax overlay to the gross cashflow projection.
2. Samples N annual-return paths from the `BootstrapReturnModel`.
3. Grows the portfolio forward one year at a time using a vectorized
   NumPy loop (O(horizon) iterations, each vectorized over N paths).
4. Evaluates the FIRE goal against every (path, year) pair in a single
   NumPy operation per year.
5. Aggregates: P(goal\_met), median FIRE year, 10/50/90 percentile
   portfolio paths.

### Vectorization strategy

The outer loop is over *years* (horizon ≤ 40), not over *paths* (N=10 000).
Each iteration is a small set of NumPy array operations on shape
``(N,)`` arrays:

```text
gross_factor = exp(portfolio_log_return[:, t])    # (N,)
gross_gain   = portfolio * (gross_factor - 1)     # (N,)
net_gain     = where(gain>0, gain*(1−cg), gain)   # (N,) — tax on gains only
portfolio    = portfolio + net_gain + contribution  # scalar contrib
```

For N=10 000, T=10 this is ~10 NumPy calls of size 10 000 = trivially fast.
The 30 s ceiling is not a concern at this scale.

### Capital-gains tax application

- Applied only on **positive** gross gains (lagerbeskatning / Abgeltungsteuer
  models zero tax on down years; loss carry-forward is out of scope).
- Uses `MonteCarloConfig.capital_gains_effective_rate` — a single blended
  rate for the combined household portfolio — not the per-entity rates from
  `TaxConfig`.  The caller chooses the blended rate (e.g., weighted average
  of `DK_DEFAULT.capital_gains_effective_rate` and
  `DE_DEFAULT.capital_gains_effective_rate` by portfolio allocation).
- This is consistent with the ADR-0013 decision that portfolio-level tax
  drag is separate from income / pension tax.

### Pension income in the goal check

Pension is deterministic (same across all paths). It is precomputed for
each projected year from the net cashflow projection (after `apply_tax`)
and the goal's vesting filter. This avoids re-evaluating the cashflow model
inside the hot loop.

### Reproducibility

The `BootstrapReturnModel` encapsulates the RNG seed. Calling
`return_model.sample_paths(years=Y, n_paths=N)` with the same seed always
produces the same arrays. The `MonteCarloResult` records `seed` and
`history_hash` for audit.

### Multi-asset portfolio

`MonteCarloConfig.asset_weights` is a dictionary mapping asset-class label
to fractional weight. The weighted portfolio log return is computed as a
linear combination of per-asset log returns before exponentiation. This is
an approximation (it ignores Jensen's inequality across assets) appropriate
for Phase 2.

## Consequences

**Positive:**

- Meets all three ACs: performance, reproducibility, output shape.
- The loop over *years* (not paths) is idiomatic NumPy and avoids the
  performance cliff of iterating Python objects at path scale.
- Pension precomputation avoids duplicating vesting logic in the hot loop.
- `run()` is a pure function; same arguments → same result.

**Negative / limitations:**

- Portfolio is modelled as a single aggregated EUR value. Separate DK/DE
  sub-portfolio accounting (e.g., ASK vs Growney) is Phase 3.
- The weighted-log-return approximation slightly overestimates diversification
  benefit. Acceptable at Phase 2 precision.
- Loss carry-forwards (DK lagerbeskatning, DE Verlustverrechnungstopf) are
  not modelled; this slightly overstates tax in bad years.
- `MonteCarloResult` stores Decimal percentile values (2 d.p.), but the
  portfolio simulation is done in `float64`. The float→Decimal conversion
  at output time introduces ≤ 0.01 EUR rounding error — negligible for
  planning purposes.

## Rejected Options

### Fully vectorized (no year loop)

Pre-compute the cumulative product of return factors
``exp(log_return[:, :t].sum(axis=1))`` for each year using
``np.cumprod`` and a single tensor operation.

**Rejected** because contributions are added each year, breaking the
clean cumulative-product formulation. A scan (prefix sum with
multiplicative carry) is possible but complex and offers no practical
speedup at T ≤ 40.

### Parallel paths (multiprocessing / joblib)

Distribute path batches across CPU cores.

**Rejected** as premature: N=10 000, T=10 already finishes in < 1 s on a
single core with NumPy vectorization. Parallelism would be re-evaluated for
T=40 and N=100 000.

### Persist `simulation_run` and `simulation_path` to the database

The issue description mentions persisting runs for repeatability and
comparison.

**Deferred** to a future issue: the schema for `simulation_run` (see
ADR-0007) is not yet defined.  `MonteCarloResult` is JSON-serialisable
via `model_dump()`, so persistence can be added without changing the
runner API.
