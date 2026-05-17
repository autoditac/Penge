"""Tests for household scenario presets."""

from __future__ import annotations

from decimal import Decimal

from penge.sim.household_scenarios import (
    DelayedPensionStartPreset,
    HigherInflationPreset,
    HigherSpendingPreset,
    IncreasedSavingsPreset,
    LowerReturnsPreset,
    OneOffExpensePreset,
    RetireInYearPreset,
    WorkReductionPreset,
    apply_scenario_preset,
    compose_scenario_presets,
)
from penge.sim.plan import project_household
from tests.sim.planning_output_helpers import household_output_plan


def test_retire_in_year_updates_household_timeline_templates() -> None:
    plan = household_output_plan()

    scenario = apply_scenario_preset(plan, RetireInYearPreset(year=2027))

    assert scenario.label == "Retire in target year"
    assert scenario.plan.members[0].retirement_year == 2027
    assert scenario.plan.bridge_templates[0].bridge_start_year == 2027
    assert scenario.plan.payout_templates[0].retirement_year == 2027
    assert "retirement_year -> 2027" in scenario.changed_assumptions


def test_retire_in_year_allows_zero_bridge_public_pension_start() -> None:
    plan = household_output_plan()

    scenario = apply_scenario_preset(plan, RetireInYearPreset(year=2035))

    assert scenario.plan.members[0].retirement_year == 2035


def test_work_reduction_splits_active_rules_from_start_year() -> None:
    plan = household_output_plan()

    scenario = apply_scenario_preset(
        plan,
        WorkReductionPreset(entity="alice", start_year=2027, fte_fraction=Decimal("0.50")),
    )
    projection = project_household(scenario.plan).cashflow_gross

    salary_by_year = {flow.year: flow.gross_salary_eur for flow in projection.flows}
    assert salary_by_year[2026] == Decimal("104040.00")
    assert salary_by_year[2027] == Decimal("53060.40")


def test_savings_inflation_spending_return_and_pension_presets_change_assumptions() -> None:
    plan = household_output_plan()

    increased = apply_scenario_preset(
        plan,
        IncreasedSavingsPreset(monthly_delta_dkk=Decimal("1000"), account_id="alice-ask"),
    )
    assert increased.plan.liquid_configs[0].annual_contribution_dkk == Decimal("32000.00")
    assert increased.plan.liquid_configs[1].annual_contribution_dkk == Decimal("10000")

    unfiltered = apply_scenario_preset(
        plan, IncreasedSavingsPreset(monthly_delta_dkk=Decimal("1200"))
    )
    assert unfiltered.plan.liquid_configs[0].annual_contribution_dkk == Decimal("27200.00")
    assert unfiltered.plan.liquid_configs[1].annual_contribution_dkk == Decimal("17200.00")

    inflation = apply_scenario_preset(plan, HigherInflationPreset(inflation_rate=Decimal("0.05")))
    assert inflation.plan.inflation_rate == Decimal("0.05")
    assert inflation.plan.spending_plan.rules[0].inflation_rate == Decimal("0.05")

    spending = apply_scenario_preset(plan, HigherSpendingPreset(factor=Decimal("1.10")))
    assert spending.plan.spending_plan.rules[0].annual_amount == Decimal("330000.00")

    returns = apply_scenario_preset(
        plan,
        LowerReturnsPreset(annual_return_delta=Decimal("-0.01")),
    )
    assert returns.plan.pension_market_return_rate == Decimal("0.03")
    assert returns.plan.liquid_configs[0].gross_annual_return_rate == Decimal("0.04")

    delayed = apply_scenario_preset(plan, DelayedPensionStartPreset(delay_years=2))
    assert delayed.plan.members[0].public_pension_start_year == 2037


def test_presets_are_composable_and_keep_labels_and_assumptions() -> None:
    plan = household_output_plan()

    scenario = compose_scenario_presets(
        plan,
        (
            OneOffExpensePreset(year=2026, amount=Decimal("50000"), expense_label="roof"),
            HigherSpendingPreset(factor=Decimal("1.05")),
        ),
        name="roof-and-spending",
        label="Roof repair and higher spending",
    )

    result = project_household(scenario.plan)
    assert scenario.name == "roof-and-spending"
    assert scenario.label == "Roof repair and higher spending"
    assert len(scenario.changed_assumptions) == 2
    assert result.spending_by_year[1].total_dkk > Decimal("300000")
