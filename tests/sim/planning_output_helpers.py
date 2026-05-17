"""Synthetic household-planning fixtures for simulation output tests."""

from __future__ import annotations

from decimal import Decimal

from penge.sim.cashflow import PensionAccrualRule, SalaryRule
from penge.sim.liquid import LiquidDepotConfig
from penge.sim.plan import (
    BridgeTemplate,
    FolkepensionTemplate,
    HouseholdMember,
    HouseholdPlan,
    PayoutTemplate,
)
from penge.sim.spending import HouseholdSpendingPlan, SpendingRule
from penge.sim.tax import DK_DEFAULT, TaxConfig


def household_output_plan(
    *,
    horizon_years: int = 12,
    bridge_start_year: int = 2028,
    ask_lifetime_deposits_dkk: Decimal = Decimal("100000"),
    ask_annual_contribution_dkk: Decimal = Decimal("20000"),
    annual_spending_dkk: Decimal = Decimal("300000"),
    pension_opening_eur: Decimal = Decimal("1000000"),
    bridge_horizon_months: int = 72,
) -> HouseholdPlan:
    """Return a compact synthetic plan that exercises output-report modules."""

    return HouseholdPlan(
        base_year=2024,
        horizon_years=horizon_years,
        inflation_rate=Decimal("0.02"),
        eur_per_dkk=Decimal("0.134"),
        pension_market_return_rate=Decimal("0.04"),
        pal_skat_rate=Decimal("0.153"),
        members=(
            HouseholdMember(
                name="alice",
                birth_year=1980,
                jurisdiction="DK",
                retirement_year=2028,
                public_pension_start_year=2035,
            ),
        ),
        salaries=(SalaryRule(entity="alice", gross_annual=Decimal("100000")),),
        pension_rules=(
            PensionAccrualRule(
                entity="alice",
                kind="annual_eur",
                annual_eur=Decimal("12000"),
                vesting_year=2035,
            ),
        ),
        pension_opening_balances={"alice": pension_opening_eur},
        tax_config=TaxConfig(regimes={"alice": DK_DEFAULT}),
        spending_plan=HouseholdSpendingPlan(
            rules=(
                SpendingRule(
                    label="living",
                    annual_amount=annual_spending_dkk,
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
                opening_balance_dkk=Decimal("900000"),
                ask_lifetime_deposits_dkk=ask_lifetime_deposits_dkk,
                annual_contribution_dkk=ask_annual_contribution_dkk,
                gross_annual_return_rate=Decimal("0.05"),
                annual_expense_ratio=Decimal("0.005"),
                tax_source="depot",
                aktieindkomst_threshold_dkk=Decimal("67500"),
            ),
            LiquidDepotConfig(
                account_id="alice-frie",
                account_type="frie_midler",
                tax_regime="realisation",
                opening_balance_dkk=Decimal("300000"),
                annual_contribution_dkk=Decimal("10000"),
                gross_annual_return_rate=Decimal("0.06"),
                annual_expense_ratio=Decimal("0.005"),
                annual_dividend_yield=Decimal("0.03"),
                tax_source="external",
                aktieindkomst_threshold_dkk=Decimal("67500"),
                opening_cost_basis_dkk=Decimal("250000"),
            ),
        ),
        bridge_templates=(
            BridgeTemplate(
                entity="alice",
                liquid_account_id="alice-frie",
                bridge_start_year=bridge_start_year,
                horizon_months=bridge_horizon_months,
                gross_annual_return_rate=Decimal("0.04"),
                annual_expense_ratio=Decimal("0.005"),
                account_type="frie_midler",
                tax_regime="realisation",
                aktieindkomst_threshold_dkk=Decimal("67500"),
                annual_dividend_yield=Decimal("0.03"),
            ),
        ),
        payout_templates=(
            PayoutTemplate(
                entity="alice",
                retirement_year=2028,
                retirement_age=65,
                livrente_fraction=Decimal("0.70"),
                ratepension_fraction=Decimal("0.25"),
                ratepension_years=15,
                annuity_factor=Decimal("4800"),
            ),
        ),
        folkepension_templates=(FolkepensionTemplate(entity="alice", civil_status="married"),),
    )
