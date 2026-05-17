"""Plain-language ASK and contribution-routing explanations."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

import pydantic

from penge.sim.routing import (
    ContributionRouter,
    MonthlyContributionSplit,
    YearlyContributionSplit,
    simulate_routing,
    simulate_routing_monthly,
)

__all__ = [
    "ContributionStrategyExplanation",
    "ContributionStrategyWarning",
    "explain_contribution_strategy",
]

_TWO_DP = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)


class ContributionStrategyWarning(pydantic.BaseModel):
    """Warning emitted by the contribution strategy explainer."""

    model_config = pydantic.ConfigDict(frozen=True)

    code: str
    message: str


class ContributionStrategyExplanation(pydantic.BaseModel):
    """Deterministic contribution-routing explanation."""

    model_config = pydantic.ConfigDict(frozen=True)

    base_year: int
    horizon_years: int
    total_to_ask_dkk: Decimal
    total_to_frie_midler_dkk: Decimal
    ask_cap_exhaustion_month: int | None
    ask_cap_exhaustion_year: int | None
    onward_monthly_ask_dkk: Decimal
    onward_monthly_frie_midler_dkk: Decimal
    yearly_splits: tuple[YearlyContributionSplit, ...]
    monthly_splits: tuple[MonthlyContributionSplit, ...]
    warnings: tuple[ContributionStrategyWarning, ...]
    summary: str


def explain_contribution_strategy(
    router: ContributionRouter,
    *,
    base_year: int,
    horizon_years: int,
) -> ContributionStrategyExplanation:
    """Explain ASK/frie-midler contribution routing over a planning horizon."""

    if horizon_years < 1:
        raise ValueError("horizon_years must be >= 1")
    yearly = simulate_routing(router, n_years=horizon_years)
    monthly = simulate_routing_monthly(router, n_months=horizon_years * 12)
    exhaustion = next((split for split in monthly if split.ask_cap_exhausted), None)
    exhaustion_month = None if exhaustion is None else exhaustion.month_number
    exhaustion_year = (
        None if exhaustion_month is None else base_year + ((exhaustion_month - 1) // 12) + 1
    )
    warnings = _warnings(router)
    total_to_ask = _q(sum((split.ask_contribution_dkk for split in yearly), Decimal("0")))
    total_to_frie = _q(sum((split.frie_midler_contribution_dkk for split in yearly), Decimal("0")))
    final_month = monthly[-1]
    explanation = ContributionStrategyExplanation(
        base_year=base_year,
        horizon_years=horizon_years,
        total_to_ask_dkk=total_to_ask,
        total_to_frie_midler_dkk=total_to_frie,
        ask_cap_exhaustion_month=exhaustion_month,
        ask_cap_exhaustion_year=exhaustion_year,
        onward_monthly_ask_dkk=final_month.ask_contribution_dkk,
        onward_monthly_frie_midler_dkk=final_month.frie_midler_contribution_dkk,
        yearly_splits=yearly,
        monthly_splits=monthly,
        warnings=warnings,
        summary="",
    )
    return explanation.model_copy(update={"summary": _summary(explanation, router)})


def _warnings(router: ContributionRouter) -> tuple[ContributionStrategyWarning, ...]:
    warnings: list[ContributionStrategyWarning] = []
    if router.ask_cumulative_deposits_dkk == router.ask_cap_dkk:
        warnings.append(
            ContributionStrategyWarning(
                code="ask_cap_already_exhausted",
                message=(
                    "Initial ASK lifetime deposits already equal the cap; "
                    "route new savings to frie midler."
                ),
            )
        )
    elif router.ask_cap_remaining_dkk <= router.monthly_contribution_dkk:
        warnings.append(
            ContributionStrategyWarning(
                code="ask_cap_exhausts_first_month",
                message="ASK cap will be exhausted in the first projected month.",
            )
        )
    return tuple(warnings)


def _summary(
    explanation: ContributionStrategyExplanation,
    router: ContributionRouter,
) -> str:
    if explanation.ask_cap_exhaustion_month is None:
        exhaustion = "ASK cap is not exhausted inside the planning horizon"
    else:
        exhaustion = (
            "ASK cap is exhausted in month "
            f"{explanation.ask_cap_exhaustion_month} "
            f"({explanation.ask_cap_exhaustion_year})"
        )
    return (
        f"Route {_q(explanation.total_to_ask_dkk)} DKK to ASK and "
        f"{_q(explanation.total_to_frie_midler_dkk)} DKK to frie midler over "
        f"{explanation.horizon_years} years. {exhaustion}. After the horizon, "
        f"the monthly split is {_q(explanation.onward_monthly_ask_dkk)} DKK to ASK "
        f"and {_q(explanation.onward_monthly_frie_midler_dkk)} DKK to frie midler "
        f"from a monthly savings budget of {_q(router.monthly_contribution_dkk)} DKK."
    )
