# 0010 — Simulation return model: historical block-bootstrap

- **Status:** Accepted
- **Date:** 2026-05-09
- **Deciders:** @autoditac
- **Tags:** sim

## Context and Problem Statement

Phase 2 of Penge models long-horizon FIRE outcomes for a DK/DE household.
The Monte-Carlo runner (issue #31), the deterministic cashflow engine
(#27), the goal model (#30), and the scenario engine (#32) all need a
return-and-inflation model that is:

1. Reproducible from a seed (so a stored projection can be re-derived
   bit-for-bit during an audit).
2. Free of forward-looking assumptions about means and volatilities
   (the household's own conviction about future returns is encoded as
   a *scenario*, not the baseline).
3. Capable of preserving the empirical autocorrelation and cross-asset
   correlation that drive sequence-of-returns risk during the early
   retirement decades.
4. Cheap enough to run thousands of paths interactively from the
   Streamlit dashboard (#33) without a worker pool.

This ADR fixes the modelling choice and the surface area of the first
public type in the new `penge.sim` package.

## Decision Drivers

- Sequence-of-returns risk: a draw of 30 IID years smooths over the
  multi-year drawdowns that actually move the FIRE date around. The
  model must let those drawdowns happen *together* across asset
  classes, so we cannot draw asset returns independently.
- Distributional uncertainty is enormous; fitting a parametric joint
  distribution on ≤60 years of monthly data overfits at the tails.
- We have monthly history for MSCI World (USD then EUR-converted),
  Bloomberg EUR Aggregate Bond, a DKK money-market proxy, and HICP
  inflation for DE and DK back to the 1990s. That is enough for a
  block bootstrap but too little for a parametric Bayesian fit.
- Trustworthy numbers > clever modelling. A bootstrap is a
  one-paragraph explanation in a runbook; a regime-switching VAR is
  not.

## Considered Options

1. **IID parametric model per asset class** — fit a multivariate
   normal (or Student-t) to log returns, draw IID years.
2. **Block-bootstrap from joint history** — draw contiguous blocks of
   real months from the joint history matrix, concatenate to the
   target horizon. Block length configurable; IID is the special case
   `block_months = 1`.
3. **Regime-switching / stochastic-volatility model** — fit a 2-state
   HMM or a GARCH-type model.

## Decision

We chose **Option 2: block bootstrap from joint monthly history**.

The first cut implements both `IID` (`block_months = 1`) and
`block_months ≥ 2` modes in a single class. Asset classes are
draw-aligned: a single sequence of month indices is sampled and used
to slice every asset class column simultaneously, which automatically
preserves cross-asset correlation in each block.

The public type is:

```python
class BootstrapReturnModel(BaseModel):
    asset_returns: Mapping[str, Sequence[Decimal]]   # monthly log returns
    inflation: Mapping[str, Sequence[Decimal]]       # monthly log inflation
    block_months: int = 12
    seed: int

    def sample_paths(
        self,
        *,
        years: int,
        n_paths: int,
    ) -> SampledPaths: ...
```

`SampledPaths` carries:

- `asset_log_returns: dict[str, ndarray]` of shape `(n_paths, years)`
- `inflation_log: dict[str, ndarray]` of shape `(n_paths, years)`
- `seed`, `block_months`, and a hash of the input history for
  reproducibility audits.

Annual returns are produced by summing 12 monthly log returns within
each year (months never split a year). `numpy.random.Generator` is
constructed from the `seed` so the same seed yields the same paths
across runs.

## Consequences

### Positive

- Reproducible: same seed → same paths, byte-for-byte. Stored
  projection results can be re-derived during a tax audit.
- Honest: never assumes a parametric form we cannot defend with our
  ≤60 years of data.
- Captures sequence-of-returns risk: realised drawdowns (2008, 2022)
  appear in proportion to their historical frequency, with their real
  cross-asset co-movements preserved.
- Cheap: 10 000 × 30-year paths run in well under a second on a
  laptop; the Streamlit dashboard can re-sample on every interaction.
- Property-testable: invariants (reproducibility, shape,
  long-run-mean preservation, autocorrelation ordering) are easy to
  pin down with `hypothesis`.

### Negative

- The bootstrap can only re-shuffle the past; it cannot generate a
  10-σ event the historical record never contained. We accept this:
  scenarios (#32) are the right place to encode "what if rates go to
  10 % for a decade" rather than the baseline distribution.
- Cross-asset correlation is preserved *within* a block but not
  *across* the block boundary. Block lengths of 12 months are large
  enough that this is a second-order effect for FIRE-horizon
  averages.

### Neutral

- The asset-class universe (MSCI World, EUR Aggregate Bonds, DKK MM
  proxy) is a configuration input, not a hard-coded list. New asset
  classes (e.g. real estate, gold) drop in by extending the input
  history dict.

## Alternatives in detail

### Option 1 — IID parametric model

Rejected because IID destroys the autocorrelation that drives
sequence-of-returns risk, and because a Gaussian (or even Student-t)
fit overstates the tightness of the joint distribution given our
short history. This would systematically underprice the probability
of "FIRE-then-back-to-work" scenarios and bias the FIRE date too
early.

### Option 3 — Regime-switching / stochastic volatility

Rejected for now because (a) we have at most ~360 monthly
observations per asset class, which is too few to reliably fit a
2-state model with 6+ free parameters per state; (b) the
interpretability cost is high — a household runbook should be able to
explain "we sampled blocks of real months from history" in one
sentence; (c) we can revisit if a future ADR shows that the
bootstrap-implied tails are clearly wrong.

## Links

- Issue #26 — feat(sim): historical-bootstrap return model
- Issue #27 — feat(sim): deterministic cashflow engine
- Issue #28 — feat(sim): tax overlay
- Issue #30 — feat(sim): goal model
- Issue #31 — feat(sim): vectorized Monte-Carlo runner
- Issue #32 — feat(sim): scenario engine
- Code: `src/penge/sim/returns.py`
- Tests: `tests/sim/test_returns.py`
- Docs: `docs/sim/return-model.md`
- ADR-0004 EUR and DKK shown in parallel (asset classes are reported
  in both currencies).
