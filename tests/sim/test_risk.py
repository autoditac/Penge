"""Tests for household planning risk registers."""

from __future__ import annotations

from decimal import Decimal

from penge.sim.balance import HouseholdBalanceSheet, HouseholdBalanceSheetRow
from penge.sim.contribution_strategy import explain_contribution_strategy
from penge.sim.plan import project_household
from penge.sim.risk import generate_risk_register
from penge.sim.routing import ContributionRouter
from tests.sim.planning_output_helpers import household_output_plan


def test_risk_register_combines_named_findings_from_planning_outputs() -> None:
    result = project_household(
        household_output_plan(
            bridge_start_year=2028,
            ask_lifetime_deposits_dkk=Decimal("135000"),
            ask_annual_contribution_dkk=Decimal("200000"),
            bridge_horizon_months=12,
        )
    )
    balance_sheet = HouseholdBalanceSheet(
        rows=(
            HouseholdBalanceSheetRow(
                year=2027,
                ask_balance_dkk=Decimal("0"),
                frie_midler_balance_dkk=Decimal("0"),
                bridge_balance_dkk=Decimal("0"),
                pension_balance_eur=Decimal("100000"),
                pension_balance_dkk=Decimal("746268.66"),
                spendable_liquidity_dkk=Decimal("0"),
                locked_pension_dkk=Decimal("746268.66"),
                total_net_worth_dkk=Decimal("746268.66"),
                annual_spending_dkk=Decimal("300000"),
                liquidity_runway_months=Decimal("0.00"),
                liquidity_depleted=True,
            ),
        )
    )
    contribution_strategy = explain_contribution_strategy(
        ContributionRouter(
            ask_cap_dkk=Decimal("100000"),
            ask_cumulative_deposits_dkk=Decimal("100000"),
            monthly_contribution_dkk=Decimal("5000"),
        ),
        base_year=2024,
        horizon_years=1,
    )

    register = generate_risk_register(
        result,
        balance_sheet=balance_sheet,
        contribution_strategy=contribution_strategy,
    )

    codes = {finding.code for finding in register.findings}
    assert {
        "liquidity_depleted",
        "locked_pension_before_access",
        "topskat_exposure",
        "ask_cap_reached",
        "ask_cap_already_exhausted",
        "bridge_depletes_early",
    } <= codes
    assert {"folkepension_reduced", "folkepension_tillaeg_fully_reduced"} & codes
    assert len(codes) == len(register.findings)
    assert all(finding.source_assumption for finding in register.findings)
    assert all(finding.next_action for finding in register.findings)
