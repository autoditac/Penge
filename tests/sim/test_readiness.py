"""Tests for retirement readiness reporting."""

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
    project_household,
)
from penge.sim.readiness import generate_readiness_report
from penge.sim.spending import HouseholdSpendingPlan, SpendingRule
from penge.sim.tax import DK_DEFAULT, TaxConfig


def _report_plan() -> HouseholdPlan:
    return HouseholdPlan(
        base_year=2024,
        horizon_years=12,
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
        pension_opening_balances={"alice": Decimal("75000")},
        tax_config=TaxConfig(regimes={"alice": DK_DEFAULT}),
        spending_plan=HouseholdSpendingPlan(
            rules=(
                SpendingRule(
                    label="living",
                    annual_amount=Decimal("300000"),
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
                annual_contribution_dkk=Decimal("20000"),
                gross_annual_return_rate=Decimal("0.05"),
                annual_expense_ratio=Decimal("0.005"),
                tax_source="depot",
                aktieindkomst_threshold_dkk=Decimal("67500"),
            ),
        ),
        bridge_templates=(
            BridgeTemplate(
                entity="alice",
                liquid_account_id="alice-ask",
                bridge_start_year=2028,
                horizon_months=72,
                gross_annual_return_rate=Decimal("0.04"),
                annual_expense_ratio=Decimal("0.005"),
                account_type="ask",
                tax_regime="lager",
                aktieindkomst_threshold_dkk=Decimal("67500"),
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


def test_readiness_report_contains_stable_markdown_sections() -> None:
    report = generate_readiness_report(project_household(_report_plan()))

    assert report.planned_retirement_year == 2028
    assert report.bridge_assessments
    assert "# Retirement readiness report" in report.markdown
    assert "## Balance sheet and liquidity runway" in report.markdown
    assert "## Tax drag summary" in report.markdown
    assert "## Assumptions" in report.markdown


def test_readiness_report_surfaces_liquidity_depletion() -> None:
    plan = _report_plan().model_copy(update={"liquid_configs": (), "bridge_templates": ()})
    report = generate_readiness_report(project_household(plan))

    assert report.conclusion == "not_ready"
    assert any(finding.code == "liquidity_depleted" for finding in report.findings)
