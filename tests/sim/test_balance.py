"""Tests for household balance sheet and liquidity runway."""

from __future__ import annotations

from decimal import Decimal

from penge.sim.balance import first_liquidity_depletion, project_balance_sheet
from penge.sim.cashflow import PensionAccrualRule, SalaryRule
from penge.sim.liquid import LiquidDepotConfig
from penge.sim.plan import BridgeTemplate, HouseholdMember, HouseholdPlan, project_household
from penge.sim.spending import HouseholdSpendingPlan, SpendingRule


def _plan() -> HouseholdPlan:
    return HouseholdPlan(
        base_year=2024,
        horizon_years=5,
        inflation_rate=Decimal("0.02"),
        eur_per_dkk=Decimal("0.134"),
        members=(
            HouseholdMember(
                name="alice",
                birth_year=1980,
                jurisdiction="DK",
                retirement_year=2026,
                public_pension_start_year=2035,
            ),
        ),
        salaries=(SalaryRule(entity="alice", gross_annual=Decimal("80000")),),
        pension_rules=(
            PensionAccrualRule(
                entity="alice",
                kind="annual_eur",
                annual_eur=Decimal("10000"),
                vesting_year=2035,
            ),
        ),
        pension_opening_balances={"alice": Decimal("50000")},
        spending_plan=HouseholdSpendingPlan(
            rules=(
                SpendingRule(
                    label="living",
                    annual_amount=Decimal("240000"),
                    currency="DKK",
                    inflation_rate=Decimal("0"),
                ),
            )
        ),
        liquid_configs=(
            LiquidDepotConfig(
                account_id="alice-ask",
                account_type="ask",
                tax_regime="lager",
                opening_balance_dkk=Decimal("400000"),
                annual_contribution_dkk=Decimal("0"),
                gross_annual_return_rate=Decimal("0.04"),
                annual_expense_ratio=Decimal("0.005"),
                tax_source="depot",
                aktieindkomst_threshold_dkk=Decimal("67500"),
            ),
        ),
        bridge_templates=(
            BridgeTemplate(
                entity="alice",
                liquid_account_id="alice-ask",
                bridge_start_year=2026,
                horizon_months=36,
                gross_annual_return_rate=Decimal("0.04"),
                annual_expense_ratio=Decimal("0.005"),
                account_type="ask",
                tax_regime="lager",
                aktieindkomst_threshold_dkk=Decimal("67500"),
            ),
        ),
    )


def test_balance_sheet_separates_liquidity_from_locked_pension() -> None:
    result = project_household(_plan())
    balance_sheet = project_balance_sheet(result)

    row = balance_sheet.rows[0]
    assert row.spendable_liquidity_dkk > Decimal("0")
    assert row.locked_pension_dkk > Decimal("0")
    assert row.total_net_worth_dkk == row.spendable_liquidity_dkk + row.locked_pension_dkk


def test_bridged_account_is_replaced_by_bridge_balance_after_start_year() -> None:
    result = project_household(_plan())
    balance_sheet = project_balance_sheet(result)
    after_bridge_start = next(row for row in balance_sheet.rows if row.year == 2027)

    assert after_bridge_start.ask_balance_dkk == Decimal("0.00")
    assert after_bridge_start.bridge_balance_dkk > Decimal("0")


def test_liquidity_runway_and_first_depletion_are_reported() -> None:
    plan = _plan().model_copy(update={"liquid_configs": (), "bridge_templates": ()})
    result = project_household(plan)
    balance_sheet = project_balance_sheet(result)

    assert balance_sheet.rows[0].liquidity_runway_months == Decimal("0.00")
    depletion = first_liquidity_depletion(balance_sheet)
    assert depletion is not None
    assert depletion.year == 2025
