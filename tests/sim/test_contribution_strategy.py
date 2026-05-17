"""Tests for ASK contribution-strategy explanations."""

from __future__ import annotations

from decimal import Decimal

import pytest

from penge.sim.contribution_strategy import explain_contribution_strategy
from penge.sim.routing import ContributionRouter


def test_contribution_strategy_explains_cap_exhaustion_and_onward_split() -> None:
    router = ContributionRouter(
        ask_cap_dkk=Decimal("100000"),
        ask_cumulative_deposits_dkk=Decimal("70000"),
        monthly_contribution_dkk=Decimal("10000"),
    )

    explanation = explain_contribution_strategy(router, base_year=2024, horizon_years=2)

    assert explanation.total_to_ask_dkk == Decimal("30000.00")
    assert explanation.total_to_frie_midler_dkk == Decimal("210000.00")
    assert explanation.ask_cap_exhaustion_month == 3
    assert explanation.ask_cap_exhaustion_year == 2025
    assert explanation.onward_monthly_ask_dkk == Decimal("0.00")
    assert explanation.onward_monthly_frie_midler_dkk == Decimal("10000.00")
    assert "ASK cap is exhausted in month 3 (2025)" in explanation.summary


def test_contribution_strategy_warns_when_cap_is_initially_exhausted() -> None:
    router = ContributionRouter(
        ask_cap_dkk=Decimal("100000"),
        ask_cumulative_deposits_dkk=Decimal("100000"),
        monthly_contribution_dkk=Decimal("5000"),
    )

    explanation = explain_contribution_strategy(router, base_year=2024, horizon_years=1)

    assert explanation.total_to_ask_dkk == Decimal("0.00")
    assert explanation.ask_cap_exhaustion_month == 1
    assert explanation.warnings[0].code == "ask_cap_already_exhausted"


def test_contribution_strategy_rejects_empty_horizon() -> None:
    router = ContributionRouter(
        ask_cap_dkk=Decimal("100000"),
        ask_cumulative_deposits_dkk=Decimal("0"),
        monthly_contribution_dkk=Decimal("5000"),
    )

    with pytest.raises(ValueError, match="horizon_years"):
        explain_contribution_strategy(router, base_year=2024, horizon_years=0)
