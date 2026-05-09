# Return model

Penge's simulation engine draws future asset returns and inflation from a
**historical block bootstrap** rather than a parametric distribution. The
rationale and trade-offs are recorded in
[ADR-0010](../decisions/0010-sim-return-model.md); this page documents the
runtime contract.

## What it does

[`BootstrapReturnModel`](https://github.com/autoditac/Penge/blob/main/src/penge/sim/returns.py)
takes a joint monthly history (asset-class log returns + country log
inflation) and produces, on demand, a batch of joint paths over a future
horizon. Within each path, contiguous blocks of real months are
concatenated; the same month-index sequence is applied to every asset class
and inflation series, which preserves the empirical cross-asset and
inflation/return correlation inside each block.

`block_months = 1` is a pure IID monthly bootstrap; `block_months = 12`
(the default) preserves a year of within-block autocorrelation, which
matters for sequence-of-returns risk in the early FIRE decades.

## Usage

```python
from decimal import Decimal

from penge.sim.returns import BootstrapReturnModel

model = BootstrapReturnModel(
    # All series must share the same length T (>= 12 months).
    asset_returns={
        "msci_world_eur": [Decimal("0.0058"), ...],   # monthly log returns
        "eur_agg_bonds":  [Decimal("0.0021"), ...],
        "dkk_money_mkt":  [Decimal("0.0001"), ...],
    },
    inflation={
        "de": [Decimal("0.0014"), ...],               # monthly log inflation
        "dk": [Decimal("0.0012"), ...],
    },
    block_months=12,
    seed=20260509,
)

paths = model.sample_paths(years=30, n_paths=10_000)
# paths.asset_log_returns["msci_world_eur"] has shape (10_000, 30)
# and contains *annual* log returns (sums of 12 monthly samples).
```

## Reproducibility

Re-running `model.sample_paths(...)` with the same `seed`, `block_months`,
and history yields identical arrays bit-for-bit. The
[`SampledPaths.history_hash`](https://github.com/autoditac/Penge/blob/main/src/penge/sim/returns.py)
field is the SHA-256 of the canonicalised input history; persist it
alongside the seed when storing a projection so an audit can detect any
silent change to the underlying history.

## Inputs are Decimal at the boundary, float64 inside the kernel

Per ADR-0010, history values are typed as `Decimal` so that exact rationals
from the ingestion layer survive config validation. Inside `sample_paths`
they are converted once to `float64`; log returns are dimensionless ratios,
not financial amounts, so this conversion is the documented split between
the audit-grade Decimal layer (amounts, FX, statutory rates) and the
numeric simulation layer.

## What it does **not** do

- It cannot produce a 10-σ event the historical record never contained.
  Tail-risk scenarios go through the scenario engine (issue #32), not the
  baseline distribution.
- It does not (yet) condition on macro state — there is no regime switch
  between "high rates" and "low rates" history. ADR-0010 documents the
  rejected alternatives and the bar for revisiting them.

## Tests

Property-based tests under
[`tests/sim/test_returns.py`](https://github.com/autoditac/Penge/blob/main/tests/sim/test_returns.py)
pin down the runtime invariants:

- Reproducibility: same seed → same arrays.
- Shape and dtype: every output array is `(n_paths, years)` `float64`.
- Cross-asset structure: identical input series produce identical output
  series (the same index sequence is applied to all assets).
- IID degenerate case: `block_months=1` removes the within-block
  autocorrelation of the input.
- Block bootstrap preserves within-block autocorrelation: with a positively
  autocorrelated history, the variance of an annual sum sampled with
  `block_months=24` exceeds the IID variance.
- Long-run mean preservation: with enough sampled months, the empirical
  monthly mean approaches the historical monthly mean (`hypothesis`
  parameterised over seeds).
