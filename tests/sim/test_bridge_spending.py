"""Tests for bridge-to-pension safe-spending planner."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

import pytest

from penge.sim.bridge_spending import (
    assess_bridge_spending,
    required_starting_capital_for_bridge_spending,
)
from penge.sim.liquid import BridgeConfig


def _bridge_config(
    *,
    account_type: Literal["ask", "frie_midler"] = "ask",
    tax_regime: Literal["lager", "realisation"] = "lager",
    starting_balance_dkk: str = "1000000",
    cost_basis_dkk: str = "1000000",
    annual_dividend_yield: str = "0",
) -> BridgeConfig:
    return BridgeConfig(
        starting_balance_dkk=Decimal(starting_balance_dkk),
        cost_basis_dkk=Decimal(cost_basis_dkk),
        horizon_months=120,
        gross_annual_return_rate=Decimal("0.05"),
        annual_expense_ratio=Decimal("0.005"),
        account_type=account_type,
        tax_regime=tax_regime,
        aktieindkomst_threshold_dkk=Decimal("67500"),
        annual_dividend_yield=Decimal(annual_dividend_yield),
    )


def test_lager_bridge_reports_sustainable_net_spending() -> None:
    result = assess_bridge_spending(
        _bridge_config(),
        target_monthly_net_spending_dkk=Decimal("8000"),
        start_year=2056,
    )

    assert result.max_monthly_net_spending_dkk > Decimal("8000")
    assert result.is_target_feasible
    assert result.depletion_month == 120
    assert result.depletion_year == 2065


def test_akkumulerende_realisation_fund_includes_withdrawal_tax() -> None:
    result = assess_bridge_spending(
        _bridge_config(
            account_type="frie_midler",
            tax_regime="realisation",
            cost_basis_dkk="600000",
        )
    )

    assert result.max_monthly_gross_withdrawal_dkk > result.max_monthly_net_spending_dkk
    assert result.total_tax_paid_dkk > Decimal("0")


def test_udloddende_realisation_fund_includes_dividend_tax() -> None:
    result = assess_bridge_spending(
        _bridge_config(
            account_type="frie_midler",
            tax_regime="realisation",
            cost_basis_dkk="600000",
            annual_dividend_yield="0.02",
        )
    )

    assert any(flow.dividend_tax_dkk > Decimal("0") for flow in result.bridge_result.monthly_flows)
    assert result.total_tax_paid_dkk > Decimal("0")


def test_required_capital_for_target_monthly_spending() -> None:
    result = required_starting_capital_for_bridge_spending(
        _bridge_config(starting_balance_dkk="100000", cost_basis_dkk="100000"),
        Decimal("8000"),
    )

    assert result.required_starting_capital_dkk is not None
    assert result.required_starting_capital_dkk > Decimal("100000")
    assert result.is_target_feasible
    assert abs(result.safety_margin_dkk or Decimal("0")) < Decimal("1")


def test_insufficient_existing_capital_explains_failure() -> None:
    result = assess_bridge_spending(
        _bridge_config(starting_balance_dkk="100000", cost_basis_dkk="100000"),
        target_monthly_net_spending_dkk=Decimal("8000"),
    )

    assert not result.is_target_feasible
    assert result.failure_reason is not None
    assert "exceeds sustainable bridge spending" in result.failure_reason


def test_rejects_non_positive_target() -> None:
    with pytest.raises(ValueError, match="must be > 0"):
        assess_bridge_spending(_bridge_config(), target_monthly_net_spending_dkk=0)
