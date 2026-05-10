"""Vectorized Monte-Carlo FIRE simulation runner.

Wires together:

1. :class:`~penge.sim.cashflow.CashflowProjection` — deterministic income
   and pension streams per entity per year.
2. :class:`~penge.sim.tax.TaxConfig` — statutory effective rates that net
   the cashflow projection and scale down portfolio returns.
3. :class:`~penge.sim.goal.GoalConfig` — the FIRE target (annual income,
   SWR rate, vesting filter).
4. :class:`~penge.sim.returns.BootstrapReturnModel` — generates N sampled
   annual-return paths via block bootstrap.

The runner is fully vectorized over paths (NumPy, no Python loop over paths)
and over years (one loop of length ``horizon_years`` with array slices).
N=10 000 paths over 30 years runs in well under 30 s on a laptop.

## Output

:class:`MonteCarloResult` contains:

- ``p_goal_met``: fraction of paths where the goal is met in some year.
- ``median_fire_year``: median calendar year of first goal-met (``None``
  if fewer than 50 % of paths meet the goal).
- ``fire_year_distribution``: histogram of first goal-met year across
  paths, keyed by calendar year (``int -> int`` count).  Paths that
  never meet the goal are not counted.
- ``p10_portfolio`` / ``p50_portfolio`` / ``p90_portfolio``: 10th / 50th /
  90th percentile portfolio values per year, as ``dict[year, Decimal]``.
- ``n_paths``, ``seed``, ``history_hash``: for audit / reproducibility.

See ``docs/decisions/0014-sim-montecarlo-runner.md`` for design rationale.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from types import MappingProxyType

import numpy as np
import pydantic

from penge.sim.cashflow import CashflowProjection
from penge.sim.goal import GoalConfig
from penge.sim.returns import BootstrapReturnModel
from penge.sim.tax import TaxConfig, apply_tax

__all__ = [
    "MonteCarloConfig",
    "MonteCarloResult",
    "run",
]

_TWO_DP = Decimal("0.01")


class MonteCarloConfig(pydantic.BaseModel):
    """Configuration for the Monte-Carlo runner.

    Args:
        n_paths: Number of independent simulation paths.  10 000 gives
            stable percentile estimates; 1 000 is faster for development.
        asset_weights: Fractional portfolio weights summing to 1.0.  Keys
            must be asset-class labels present in the
            :class:`~penge.sim.returns.BootstrapReturnModel`'s
            ``asset_returns`` dict.
        initial_portfolio_eur: Starting portfolio value (EUR) at
            ``cashflow.config.base_year``.
        capital_gains_effective_rate: Effective tax rate on positive annual
            portfolio gains (lagerbeskatning + Abgeltungsteuer blended).
            Applied to gross portfolio gains each year; losses are
            passed through untaxed.  Set to ``Decimal("0")`` for gross
            (pre-tax) portfolio growth.
        entities: Entity identifiers whose pension and contributions are
            included in the portfolio path.  Empty tuple = all entities.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    n_paths: int = pydantic.Field(default=10_000, ge=1)
    asset_weights: Mapping[str, Decimal]
    initial_portfolio_eur: Decimal
    capital_gains_effective_rate: Decimal = Decimal("0.27")
    entities: tuple[str, ...] = ()

    @pydantic.field_validator(
        "initial_portfolio_eur", "capital_gains_effective_rate", mode="before"
    )
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return Decimal(str(v))

    @pydantic.field_validator("asset_weights", mode="before")
    @classmethod
    def _coerce_weights(cls, v: object) -> Mapping[str, Decimal]:
        if not isinstance(v, Mapping):
            raise ValueError("asset_weights must be a mapping")
        return MappingProxyType({k: Decimal(str(val)) for k, val in v.items()})

    @pydantic.model_validator(mode="after")
    def _validate(self) -> MonteCarloConfig:
        if not self.asset_weights:
            raise ValueError("asset_weights must not be empty")
        for label, w in self.asset_weights.items():
            if w < 0:
                raise ValueError(f"asset_weights[{label!r}] must be >= 0, got {w}")
            if w > Decimal("1"):
                raise ValueError(f"asset_weights[{label!r}] must be <= 1, got {w}")
        weight_sum = sum(self.asset_weights.values())
        if abs(weight_sum - Decimal("1")) > Decimal("0.0001"):
            raise ValueError(f"asset_weights must sum to 1, got {weight_sum}")
        if self.initial_portfolio_eur < 0:
            raise ValueError("initial_portfolio_eur must be >= 0")
        if not (Decimal("0") <= self.capital_gains_effective_rate < Decimal("1")):
            raise ValueError("capital_gains_effective_rate must be in [0, 1)")
        return self


class MonteCarloResult(pydantic.BaseModel):
    """Output of :func:`run`.

    Args:
        p_goal_met: Fraction of paths where the FIRE goal is met in some
            projected year (in ``[0, 1]``).
        median_fire_year: Median calendar year of first goal-met across all
            paths that meet the goal.  ``None`` if fewer than 50 % of paths
            meet the goal.
        fire_year_distribution: Histogram of first goal-met year across
            paths, keyed by calendar year.  Paths that never meet the
            goal are not represented.  Always non-empty when at least
            one path meets the goal; empty otherwise.
        p10_portfolio: 10th-percentile portfolio value (EUR) keyed by
            calendar year.
        p50_portfolio: 50th-percentile portfolio value (EUR).
        p90_portfolio: 90th-percentile portfolio value (EUR).
        n_paths: Number of paths used in this run.
        seed: RNG seed (from the return model).
        history_hash: SHA-256 of the return-model history, for audit.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    p_goal_met: Decimal
    median_fire_year: int | None
    fire_year_distribution: dict[int, int] = pydantic.Field(default_factory=dict)
    p10_portfolio: dict[int, Decimal]
    p50_portfolio: dict[int, Decimal]
    p90_portfolio: dict[int, Decimal]
    n_paths: int
    seed: int
    history_hash: str


def run(
    cashflow: CashflowProjection,
    tax_config: TaxConfig,
    goal: GoalConfig,
    return_model: BootstrapReturnModel,
    mc_config: MonteCarloConfig,
) -> MonteCarloResult:
    """Run the vectorized Monte-Carlo FIRE simulation.

    Args:
        cashflow: Gross cashflow projection (output of
            :func:`~penge.sim.cashflow.project`).  The runner applies
            *tax_config* internally so do NOT pre-apply tax.
        tax_config: Tax configuration.  Applied via
            :func:`~penge.sim.tax.apply_tax` to net the cashflow flows;
            ``capital_gains_effective_rate`` from per-entity regimes is
            ignored here — use ``mc_config.capital_gains_effective_rate``
            for the combined portfolio rate.
        goal: FIRE goal definition.
        return_model: Fitted block-bootstrap model.
        mc_config: Runner configuration (paths, weights, initial portfolio).

    Returns:
        A :class:`MonteCarloResult` with goal statistics and percentile paths.

    Raises:
        ValueError: If *mc_config.asset_weights* contains keys not present
            in *return_model.asset_returns*.
    """
    cfg = cashflow.config
    horizon = cfg.horizon_years
    n_paths = mc_config.n_paths

    # Validate asset labels
    unknown = set(mc_config.asset_weights) - set(return_model.asset_returns)
    if unknown:
        raise ValueError(f"Unknown asset labels in asset_weights: {unknown}")

    # Apply tax overlay to get net cashflow flows
    net_cashflow = apply_tax(cashflow, tax_config)

    # Build entities to include
    entities = list(mc_config.entities) if mc_config.entities else net_cashflow.entities()

    # Extract annual contributions and pension per year (deterministic)
    years_list = net_cashflow.years()
    contrib_by_year = _build_contributions(net_cashflow, entities, years_list)
    pension_by_year = _build_cumulative_pension(net_cashflow, entities, years_list, goal)

    # Sample return paths: shape (n_paths, horizon)
    paths = return_model.sample_paths(years=horizon, n_paths=n_paths)

    # Compute weighted portfolio log return: shape (n_paths, horizon)
    portfolio_log_return = np.zeros((n_paths, horizon), dtype=np.float64)
    for label, weight in mc_config.asset_weights.items():
        portfolio_log_return += float(weight) * paths.asset_log_returns[label]

    # Portfolio growth loop (vectorized over paths)
    cg_rate = float(mc_config.capital_gains_effective_rate)
    portfolio = np.full(n_paths, float(mc_config.initial_portfolio_eur), dtype=np.float64)

    # Store per-year portfolio for percentile calculation: shape (n_paths, horizon)
    portfolio_paths = np.zeros((n_paths, horizon), dtype=np.float64)

    target = float(goal.target_annual_eur)
    swr = float(goal.swr_rate)

    # goal_met_year[i] = first year index (0-based) where goal is met, or -1
    goal_met_year_idx = np.full(n_paths, -1, dtype=np.int64)

    for t in range(horizon):
        year = cfg.base_year + t + 1
        gross_factor = np.exp(portfolio_log_return[:, t])
        gross_gain = portfolio * (gross_factor - 1.0)
        # Apply capital-gains tax only on positive gains
        net_gain = np.where(gross_gain > 0, gross_gain * (1.0 - cg_rate), gross_gain)
        portfolio = portfolio + net_gain + contrib_by_year[t]

        portfolio_paths[:, t] = portfolio

        # Check goal for paths not yet met
        if year in pension_by_year:
            pension = pension_by_year[year]
            swr_income = swr * portfolio
            total_income = swr_income + pension
            not_yet_met = goal_met_year_idx == -1
            newly_met = not_yet_met & (total_income >= target)
            goal_met_year_idx[newly_met] = t

    # Compute results
    met_mask = goal_met_year_idx >= 0
    p_goal_met = Decimal(str(round(float(met_mask.mean()), 6)))

    median_fire_year: int | None = None
    fire_year_distribution = _build_fire_year_distribution(
        goal_met_year_idx, met_mask, base_year=cfg.base_year
    )
    if met_mask.sum() >= n_paths / 2:
        fire_indices = goal_met_year_idx[met_mask]
        # Round half-up (ceil) so fractional medians map to the next worse year,
        # which is the conservative choice for FIRE planning.
        median_idx = int(np.ceil(np.median(fire_indices)))
        median_fire_year = cfg.base_year + median_idx + 1

    # Percentile portfolio paths
    p10 = np.percentile(portfolio_paths, 10, axis=0)
    p50 = np.percentile(portfolio_paths, 50, axis=0)
    p90 = np.percentile(portfolio_paths, 90, axis=0)

    p10_portfolio = {years_list[t]: Decimal(str(round(p10[t], 2))) for t in range(horizon)}
    p50_portfolio = {years_list[t]: Decimal(str(round(p50[t], 2))) for t in range(horizon)}
    p90_portfolio = {years_list[t]: Decimal(str(round(p90[t], 2))) for t in range(horizon)}

    return MonteCarloResult(
        p_goal_met=p_goal_met,
        median_fire_year=median_fire_year,
        fire_year_distribution=fire_year_distribution,
        p10_portfolio=p10_portfolio,
        p50_portfolio=p50_portfolio,
        p90_portfolio=p90_portfolio,
        n_paths=n_paths,
        seed=return_model.seed,
        history_hash=paths.history_hash,
    )


def _build_fire_year_distribution(
    goal_met_year_idx: np.ndarray,
    met_mask: np.ndarray,
    *,
    base_year: int,
) -> dict[int, int]:
    """Histogram of first-goal-met calendar year across paths.

    Returns an empty dict when no path met the goal.
    """
    if not met_mask.any():
        return {}
    fire_indices = goal_met_year_idx[met_mask]
    unique, counts = np.unique(fire_indices, return_counts=True)
    return {
        int(base_year + int(idx) + 1): int(count) for idx, count in zip(unique, counts, strict=True)
    }


def _build_contributions(
    net_cashflow: CashflowProjection,
    entities: list[str],
    years_list: list[int],
) -> list[float]:
    """Annual total liquid contribution across all entities, in EUR."""
    result: list[float] = []
    for year in years_list:
        total = sum(
            float(f.liquid_contribution_eur)
            for f in net_cashflow.by_year(year)
            if f.entity in entities
        )
        result.append(total)
    return result


def _build_cumulative_pension(
    net_cashflow: CashflowProjection,
    entities: list[str],
    years_list: list[int],
    goal: GoalConfig,
) -> dict[int, float]:
    """Cumulative pension income (post-tax, vesting-filtered) per year."""
    vesting_by_entity: dict[str, list[int]] = {e: [] for e in entities}
    for rule in net_cashflow.config.pension_rules:
        if rule.entity in vesting_by_entity:
            vesting_by_entity[rule.entity].append(rule.vesting_year)

    result: dict[int, float] = {}
    for year in years_list:
        pension = 0.0
        for flow in net_cashflow.by_year(year):
            if flow.entity not in entities:
                continue
            if goal.require_all_vested:
                vesting_years = vesting_by_entity.get(flow.entity, [])
                if vesting_years and all(vy <= year for vy in vesting_years):
                    pension += float(flow.cumulative_pension_eur)
            else:
                pension += float(flow.cumulative_pension_eur)
        result[year] = pension
    return result
