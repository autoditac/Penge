"""FIRE goal model — evaluates whether a target income can be sustained.

The goal is expressed as a target annual income (in EUR) that the household
wants to maintain from a chosen retirement year onward.  Available income
sources at year *T* are:

1. **Safe withdrawal** — ``swr_rate * liquid_portfolio_value`` from the joint
   liquid portfolio (e.g. Nordnet + Growney), where the portfolio value is
   provided by the caller (Monte-Carlo or deterministic accumulation).
2. **Pension income** — pension entitlements that have vested (i.e. their
   ``vesting_year <= T``), read from a :class:`~penge.sim.cashflow.CashflowProjection`.

A goal is *met* in year *T* when total income >= target.
:func:`evaluate` scans all projected years and returns the first year the
goal is met, or ``None`` if it is never met within the horizon.

The goal definition is a plain Pydantic model and round-trips to/from YAML
or JSON via ``model.model_dump()`` / ``GoalConfig.model_validate(d)``.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal

import pydantic

from penge.sim.cashflow import CashflowProjection

__all__ = [
    "GoalConfig",
    "GoalResult",
    "evaluate",
]


class GoalConfig(pydantic.BaseModel):
    """Configurable FIRE goal definition.

    Args:
        target_annual_eur: Annual income the household wants to replace
            (in EUR).  Typically Frau's projected net Beamtin salary in the
            retirement year, or another explicit target.
        swr_rate: Safe withdrawal rate as a fraction (e.g. ``Decimal("0.0325")``
            for 3.25 %).  Applied to the liquid portfolio value each year.
        entities: Entity identifiers whose pension entitlements count toward
            the goal.  Empty means *all* entities in the projection.
        require_all_vested: If ``True``, an entity's cumulative pension only
            counts toward the goal in year *T* when **every** pension rule
            for that entity has ``vesting_year <= T`` (since
            ``cumulative_pension_eur`` is an aggregate across rules and is not
            split per-rule).  If ``False``, all cumulative pension is counted
            regardless of vesting (useful for sensitivity analysis).
    """

    model_config = pydantic.ConfigDict(frozen=True)

    target_annual_eur: Decimal
    swr_rate: Decimal = Decimal("0.0325")
    entities: tuple[str, ...] = ()
    require_all_vested: bool = True

    @pydantic.field_validator("target_annual_eur", "swr_rate", mode="before")
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return Decimal(str(v))

    @pydantic.model_validator(mode="after")
    def _validate(self) -> GoalConfig:
        if self.target_annual_eur <= 0:
            raise ValueError("target_annual_eur must be positive")
        if not (Decimal("0") < self.swr_rate <= Decimal("1")):
            raise ValueError("swr_rate must be in (0, 1]")
        return self


class GoalResult(pydantic.BaseModel):
    """Output of :func:`evaluate`.

    Args:
        goal_met: Whether the goal is met at any year within the horizon.
        year: The first calendar year in which the goal is met, or ``None``.
        surplus_eur: Income minus target in *year* (positive = surplus,
            negative = shortfall).  When ``goal_met`` is ``False`` this is
            the shortfall in the *last* projected year.
        total_income_eur: Total projected income (SWR + pension) in *year*
            (or in the last projected year when the goal is not met).
    """

    model_config = pydantic.ConfigDict(frozen=True)

    goal_met: bool
    year: int | None
    surplus_eur: Decimal
    total_income_eur: Decimal


def _validate_portfolio_years(
    portfolio_by_year: Sequence[tuple[int, Decimal]],
    projection: CashflowProjection,
) -> None:
    if not portfolio_by_year:
        raise ValueError("portfolio_by_year must not be empty")
    projection_years = {f.year for f in projection.flows}
    last_year = -(10**9)
    for year, _ in portfolio_by_year:
        if year <= last_year:
            raise ValueError("portfolio_by_year must be in strictly ascending year order")
        if year not in projection_years:
            raise ValueError(f"portfolio year {year} is not in the projection")
        last_year = year


def evaluate(
    goal: GoalConfig,
    projection: CashflowProjection,
    portfolio_by_year: Sequence[tuple[int, Decimal]],
) -> GoalResult:
    """Evaluate a FIRE goal against a cashflow projection and portfolio path.

    For each (year, portfolio_value) pair in *portfolio_by_year*, the function
    computes::

        swr_income   = goal.swr_rate * portfolio_value
        pension_income = sum of cumulative_pension_eur for relevant entities
                         (filtered by vesting_year if require_all_vested)
        total_income = swr_income + pension_income

    The first year where ``total_income >= goal.target_annual_eur`` is
    returned as the goal-met year.

    Args:
        goal: Goal configuration.
        projection: A :class:`~penge.sim.cashflow.CashflowProjection`
            produced by :func:`~penge.sim.cashflow.project`.  Used to read
            cumulative pension entitlements and vesting years.
        portfolio_by_year: Sequence of ``(year, liquid_portfolio_value_eur)``
            pairs in ascending year order.  The years must be a subset of the
            years in *projection*.

    Returns:
        A :class:`GoalResult` with ``goal_met``, ``year``, ``surplus_eur``,
        and ``total_income_eur``.

    Raises:
        ValueError: If *portfolio_by_year* is empty.
    """
    if not portfolio_by_year:
        raise ValueError("portfolio_by_year must not be empty")

    _validate_portfolio_years(portfolio_by_year, projection)

    entities = list(goal.entities) if goal.entities else projection.entities()

    # For require_all_vested: all pension rules for an entity must have vested.
    # Build per-entity list of vesting years from the config.
    vesting_by_entity: dict[str, list[int]] = {e: [] for e in entities}
    for rule in projection.config.pension_rules:
        if rule.entity in vesting_by_entity:
            vesting_by_entity[rule.entity].append(rule.vesting_year)

    last_income = Decimal("0")
    last_surplus = Decimal("0")

    for year, portfolio_value in portfolio_by_year:
        swr_income = (goal.swr_rate * portfolio_value).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

        pension_income = Decimal("0")
        for flow in projection.by_year(year):
            if flow.entity not in entities:
                continue
            if goal.require_all_vested:
                # cumulative_pension_eur is the aggregate of all pension rules;
                # count it only if every rule for this entity has vested.
                vesting_years = vesting_by_entity.get(flow.entity, [])
                if vesting_years and all(vy <= year for vy in vesting_years):
                    pension_income += flow.cumulative_pension_eur
            else:
                pension_income += flow.cumulative_pension_eur

        total_income = swr_income + pension_income
        surplus = total_income - goal.target_annual_eur
        last_income = total_income
        last_surplus = surplus

        if surplus >= Decimal("0"):
            return GoalResult(
                goal_met=True,
                year=year,
                surplus_eur=surplus,
                total_income_eur=total_income,
            )

    # Goal never met within the horizon
    return GoalResult(
        goal_met=False,
        year=None,
        surplus_eur=last_surplus,
        total_income_eur=last_income,
    )
