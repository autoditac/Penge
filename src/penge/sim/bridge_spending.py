"""Bridge-to-pension safe-spending planner.

Builds on :mod:`penge.sim.liquid` bridge decumulation to answer two household
questions: how much net monthly spending the current bridge capital supports,
and how much starting capital is required for a target monthly net spend.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

import pydantic

from penge.sim._decimal_utils import to_decimal as _to_decimal
from penge.sim.liquid import BridgeConfig, BridgeResult, compute_bridge_pmt

__all__ = [
    "BridgeSafeSpendingResult",
    "assess_bridge_spending",
    "required_starting_capital_for_bridge_spending",
    "summarize_bridge_result",
]

_TWO_DP = Decimal("0.01")
_SEARCH_ITERATIONS = 60


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)


class BridgeSafeSpendingResult(pydantic.BaseModel):
    """Safe-spending output for one bridge configuration.

    Args:
        starting_balance_dkk: Starting bridge capital used for this result.
        cost_basis_dkk: Cost basis paired with ``starting_balance_dkk``.
        horizon_months: Bridge horizon in months.
        max_monthly_gross_withdrawal_dkk: Sustainable gross monthly withdrawal.
        max_monthly_net_spending_dkk: Sustainable net monthly spending.
        target_monthly_net_spending_dkk: Optional target net monthly spending.
        required_starting_capital_dkk: Capital required to meet the target, if searched.
        is_target_feasible: Whether the target fits the starting capital/result.
        safety_margin_dkk: ``max_monthly_net_spending_dkk - target`` when a target is set.
        depletion_month: Month where the model reaches the depletion point.
        depletion_year: Calendar year for ``depletion_month`` when ``start_year`` is supplied.
        final_balance_dkk: Final bridge depot balance after the horizon.
        total_tax_paid_dkk: Total bridge taxes over the horizon.
        failure_reason: Human-readable explanation when the target is not feasible.
        bridge_result: Full underlying bridge simulation.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    starting_balance_dkk: Decimal
    cost_basis_dkk: Decimal
    horizon_months: int
    max_monthly_gross_withdrawal_dkk: Decimal
    max_monthly_net_spending_dkk: Decimal
    target_monthly_net_spending_dkk: Decimal | None = None
    required_starting_capital_dkk: Decimal | None = None
    is_target_feasible: bool
    safety_margin_dkk: Decimal | None = None
    depletion_month: int
    depletion_year: int | None = None
    final_balance_dkk: Decimal
    total_tax_paid_dkk: Decimal
    failure_reason: str | None = None
    bridge_result: BridgeResult


def assess_bridge_spending(
    config: BridgeConfig,
    *,
    target_monthly_net_spending_dkk: Decimal | int | str | None = None,
    start_year: int | None = None,
) -> BridgeSafeSpendingResult:
    """Assess maximum sustainable monthly net spending for existing bridge capital.

    Args:
        config: Bridge decumulation config.
        target_monthly_net_spending_dkk: Optional target monthly net spend to compare.
        start_year: Optional first bridge calendar year, used to report depletion year.

    Returns:
        A :class:`BridgeSafeSpendingResult`.
    """

    target = (
        None
        if target_monthly_net_spending_dkk is None
        else _to_decimal(target_monthly_net_spending_dkk)
    )
    if target is not None and target <= Decimal("0"):
        raise ValueError("target_monthly_net_spending_dkk must be > 0")

    bridge_result = compute_bridge_pmt(config)
    return summarize_bridge_result(
        bridge_result,
        starting_balance_dkk=config.starting_balance_dkk,
        cost_basis_dkk=config.cost_basis_dkk,
        target_monthly_net_spending_dkk=target,
        start_year=start_year,
    )


def summarize_bridge_result(
    bridge_result: BridgeResult,
    *,
    starting_balance_dkk: Decimal | int | str,
    cost_basis_dkk: Decimal | int | str,
    target_monthly_net_spending_dkk: Decimal | int | str | None = None,
    start_year: int | None = None,
) -> BridgeSafeSpendingResult:
    """Summarize an already-computed bridge result as safe-spending output."""

    target = (
        None
        if target_monthly_net_spending_dkk is None
        else _to_decimal(target_monthly_net_spending_dkk)
    )
    if target is not None and target <= Decimal("0"):
        raise ValueError("target_monthly_net_spending_dkk must be > 0")

    max_net = bridge_result.monthly_net_to_pocket_dkk
    safety_margin = None if target is None else _q(max_net - target)
    feasible = target is None or (safety_margin is not None and safety_margin >= Decimal("0"))
    depletion_month = _depletion_month(bridge_result)
    failure_reason = None
    if not feasible and target is not None:
        failure_reason = (
            f"Target {target} DKK/month exceeds sustainable bridge spending "
            f"{max_net} DKK/month for starting capital {starting_balance_dkk} DKK."
        )

    return BridgeSafeSpendingResult(
        starting_balance_dkk=_to_decimal(starting_balance_dkk),
        cost_basis_dkk=_to_decimal(cost_basis_dkk),
        horizon_months=len(bridge_result.monthly_flows),
        max_monthly_gross_withdrawal_dkk=bridge_result.monthly_gross_withdrawal_dkk,
        max_monthly_net_spending_dkk=max_net,
        target_monthly_net_spending_dkk=target,
        required_starting_capital_dkk=None,
        is_target_feasible=feasible,
        safety_margin_dkk=safety_margin,
        depletion_month=depletion_month,
        depletion_year=_depletion_year(start_year, depletion_month),
        final_balance_dkk=bridge_result.final_balance_dkk,
        total_tax_paid_dkk=bridge_result.total_tax_paid_dkk,
        failure_reason=failure_reason,
        bridge_result=bridge_result,
    )


def required_starting_capital_for_bridge_spending(
    config: BridgeConfig,
    target_monthly_net_spending_dkk: Decimal | int | str,
    *,
    start_year: int | None = None,
) -> BridgeSafeSpendingResult:
    """Find starting bridge capital required for a target monthly net spend.

    The search keeps the input config's realisation cost-basis ratio.  For
    lager/ASK bridge configs the searched cost basis is reset to the searched
    balance because gains are marked to market annually.
    """

    target = _to_decimal(target_monthly_net_spending_dkk)
    if target <= Decimal("0"):
        raise ValueError("target_monthly_net_spending_dkk must be > 0")

    lo = Decimal("0.01")
    hi = max(config.starting_balance_dkk, target * Decimal(str(config.horizon_months)))
    hi_config = _with_starting_balance(config, hi)
    hi_result = assess_bridge_spending(
        hi_config,
        target_monthly_net_spending_dkk=target,
        start_year=start_year,
    )
    for _ in range(20):
        if hi_result.is_target_feasible:
            break
        hi = _q(hi * Decimal("2"))
        hi_config = _with_starting_balance(config, hi)
        hi_result = assess_bridge_spending(
            hi_config,
            target_monthly_net_spending_dkk=target,
            start_year=start_year,
        )
    else:
        raise ValueError("could not bracket required bridge capital for target spending")

    for _ in range(_SEARCH_ITERATIONS):
        mid = _q((lo + hi) / Decimal("2"))
        mid_result = assess_bridge_spending(
            _with_starting_balance(config, mid),
            target_monthly_net_spending_dkk=target,
            start_year=start_year,
        )
        if mid_result.is_target_feasible:
            hi = mid
        else:
            lo = mid

    required = _q(hi)
    final_config = _with_starting_balance(config, required)
    final_result = assess_bridge_spending(
        final_config,
        target_monthly_net_spending_dkk=target,
        start_year=start_year,
    )
    return final_result.model_copy(update={"required_starting_capital_dkk": required})


def _with_starting_balance(config: BridgeConfig, starting_balance_dkk: Decimal) -> BridgeConfig:
    if config.tax_regime == "realisation":
        basis_ratio = config.cost_basis_dkk / config.starting_balance_dkk
        cost_basis = _q(starting_balance_dkk * basis_ratio)
    else:
        cost_basis = starting_balance_dkk
    return BridgeConfig(
        starting_balance_dkk=starting_balance_dkk,
        cost_basis_dkk=cost_basis,
        horizon_months=config.horizon_months,
        gross_annual_return_rate=config.gross_annual_return_rate,
        annual_expense_ratio=config.annual_expense_ratio,
        account_type=config.account_type,
        tax_regime=config.tax_regime,
        aktieindkomst_threshold_dkk=config.aktieindkomst_threshold_dkk,
        annual_dividend_yield=config.annual_dividend_yield,
    )


def _depletion_month(result: BridgeResult) -> int:
    for flow in result.monthly_flows:
        if flow.closing_balance_dkk <= Decimal("0"):
            return flow.month
    return result.monthly_flows[-1].month if result.monthly_flows else 0


def _depletion_year(start_year: int | None, depletion_month: int) -> int | None:
    if start_year is None or depletion_month < 1:
        return None
    return start_year + ((depletion_month - 1) // 12)
