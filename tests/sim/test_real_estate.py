"""Tests for real-estate and mortgage planning projections."""

from __future__ import annotations

from decimal import Decimal

from penge.sim.balance import project_balance_sheet
from penge.sim.household_scenarios import HomePurchasePreset, apply_scenario_preset
from penge.sim.plan import project_household
from penge.sim.real_estate import MortgageConfig, PropertyAssetConfig, project_real_estate
from penge.sim.stress import default_stress_tests, run_stress_tests
from tests.sim.planning_output_helpers import household_output_plan


def test_project_real_estate_tracks_value_debt_costs_and_sale() -> None:
    property_config = PropertyAssetConfig(
        property_id="home",
        label="Family home",
        start_year=2025,
        value_dkk=Decimal("4000000"),
        annual_value_growth_rate=Decimal("0.02"),
        annual_recurring_cost_dkk=Decimal("30000"),
        sale_year=2028,
        sale_cost_rate=Decimal("0.02"),
    )
    mortgage = MortgageConfig(
        mortgage_id="home-loan",
        property_id="home",
        start_year=2025,
        principal_dkk=Decimal("2500000"),
        annual_interest_rate=Decimal("0.03"),
        annual_amortization_dkk=Decimal("100000"),
    )

    projection = project_real_estate(
        (property_config,),
        (mortgage,),
        base_year=2024,
        horizon_years=5,
    )[0]

    first = projection.rows[0]
    assert first.property_value_dkk == Decimal("4000000.00")
    assert first.mortgage_balance_dkk == Decimal("2400000.00")
    assert first.interest_paid_dkk == Decimal("75000.00")
    sale = next(row for row in projection.rows if row.year == 2028)
    assert sale.property_value_dkk == Decimal("0")
    assert sale.mortgage_balance_dkk == Decimal("0")
    assert sale.sale_proceeds_dkk > Decimal("1500000")


def test_household_balance_sheet_includes_home_equity_but_excludes_it_from_liquidity() -> None:
    plan = household_output_plan().model_copy(
        update={
            "real_estate_assets": (
                PropertyAssetConfig(
                    property_id="home",
                    label="Family home",
                    start_year=2025,
                    value_dkk=Decimal("3000000"),
                    annual_recurring_cost_dkk=Decimal("24000"),
                ),
            ),
            "mortgages": (
                MortgageConfig(
                    mortgage_id="home-loan",
                    property_id="home",
                    start_year=2025,
                    principal_dkk=Decimal("2000000"),
                    annual_interest_rate=Decimal("0.04"),
                    annual_amortization_dkk=Decimal("50000"),
                ),
            ),
        }
    )

    balance = project_balance_sheet(project_household(plan))
    row = balance.rows[0]

    assert row.home_equity_dkk == Decimal("1050000.00")
    assert row.mortgage_debt_dkk == Decimal("1950000.00")
    assert row.housing_costs_dkk == Decimal("104000.00")
    assert row.total_net_worth_dkk > row.spendable_liquidity_dkk + row.locked_pension_dkk


def test_home_purchase_preset_and_mortgage_stress_are_available() -> None:
    plan = household_output_plan()

    scenario = apply_scenario_preset(
        plan,
        HomePurchasePreset(
            property_id="home",
            label_override="Family home",
            start_year=2027,
            value_dkk=Decimal("3500000"),
            mortgage_principal_dkk=Decimal("2500000"),
            annual_interest_rate=Decimal("0.035"),
            annual_amortization_dkk=Decimal("80000"),
            annual_recurring_cost_dkk=Decimal("25000"),
            purchase_cost_dkk=Decimal("120000"),
        ),
    )
    specs = default_stress_tests(scenario.plan)
    pack = run_stress_tests(scenario.plan, specs)

    assert scenario.plan.real_estate_assets[0].property_id == "home"
    assert scenario.plan.mortgages[0].annual_interest_rate == Decimal("0.035")
    assert "higher_mortgage_rate" in {spec.name for spec in specs}
    assert any(result.name == "higher_mortgage_rate" for result in pack.results)
