"""Tests for penge.sim.cashflow — deterministic cashflow projection engine.

All fixtures use synthetic data only.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

import pydantic
import pytest

from penge.sim.cashflow import (
    CashflowConfig,
    CashflowError,
    CashflowProjection,
    ContributionRule,
    PensionAccrualRule,
    SalaryRule,
    project,
)

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _salary(
    entity: str = "alice",
    currency: Literal["EUR", "DKK"] = "EUR",
    gross_annual: str = "60000",
    real_wage_growth: str = "0",
) -> SalaryRule:
    return SalaryRule(
        entity=entity,
        currency=currency,
        gross_annual=Decimal(gross_annual),
        real_wage_growth=Decimal(real_wage_growth),
    )


def _contrib(
    entity: str = "alice",
    currency: Literal["EUR", "DKK"] = "EUR",
    annual: str = "12000",
    index: bool = True,
) -> ContributionRule:
    return ContributionRule(
        entity=entity,
        currency=currency,
        annual=Decimal(annual),
        index_to_inflation=index,
    )


def _dc_pension(
    entity: str = "alice",
    fraction: str = "0.21",
    vesting_year: int = 2060,
) -> PensionAccrualRule:
    return PensionAccrualRule(
        entity=entity,
        kind="dc_fraction",
        dc_fraction=Decimal(fraction),
        vesting_year=vesting_year,
    )


def _annual_pension(
    entity: str = "alice",
    annual_eur: str = "2000",
    index: bool = True,
    vesting_year: int = 2060,
) -> PensionAccrualRule:
    return PensionAccrualRule(
        entity=entity,
        kind="annual_eur",
        annual_eur=Decimal(annual_eur),
        index_accrual_to_inflation=index,
        vesting_year=vesting_year,
    )


def _config(
    base_year: int = 2024,
    horizon_years: int = 5,
    inflation_rate: str = "0.02",
    eur_per_dkk: str = "0.134",
    salaries: tuple[SalaryRule, ...] = (),
    contributions: tuple[ContributionRule, ...] = (),
    pension_rules: tuple[PensionAccrualRule, ...] = (),
) -> CashflowConfig:
    return CashflowConfig(
        base_year=base_year,
        horizon_years=horizon_years,
        inflation_rate=Decimal(inflation_rate),
        eur_per_dkk=Decimal(eur_per_dkk),
        salaries=salaries,
        contributions=contributions,
        pension_rules=pension_rules,
    )


# ---------------------------------------------------------------------------
# TestProjectionShape
# ---------------------------------------------------------------------------


class TestProjectionShape:
    def test_single_entity_yields_horizon_years_flows(self) -> None:
        cfg = _config(
            horizon_years=5,
            salaries=(_salary(),),
            contributions=(_contrib(),),
        )
        proj = project(cfg)
        assert len(proj.flows) == 5

    def test_two_entities_yields_two_times_horizon_flows(self) -> None:
        cfg = _config(
            horizon_years=3,
            salaries=(_salary("alice"), _salary("bob")),
        )
        proj = project(cfg)
        assert len(proj.flows) == 6

    def test_years_are_base_year_plus_1_through_horizon(self) -> None:
        cfg = _config(base_year=2024, horizon_years=4, salaries=(_salary(),))
        proj = project(cfg)
        assert proj.years() == [2025, 2026, 2027, 2028]

    def test_entities_returns_sorted_unique_names(self) -> None:
        cfg = _config(
            salaries=(_salary("bob"), _salary("alice")),
        )
        proj = project(cfg)
        assert proj.entities() == ["alice", "bob"]

    def test_by_year_filters_correctly(self) -> None:
        cfg = _config(horizon_years=3, salaries=(_salary("a"), _salary("b")))
        proj = project(cfg)
        year_flows = proj.by_year(2026)
        assert all(f.year == 2026 for f in year_flows)
        assert len(year_flows) == 2

    def test_by_entity_filters_correctly(self) -> None:
        cfg = _config(horizon_years=3, salaries=(_salary("alice"), _salary("bob")))
        proj = project(cfg)
        alice_flows = proj.by_entity("alice")
        assert all(f.entity == "alice" for f in alice_flows)
        assert len(alice_flows) == 3

    def test_returns_cashflow_projection(self) -> None:
        cfg = _config(salaries=(_salary(),))
        assert isinstance(project(cfg), CashflowProjection)


# ---------------------------------------------------------------------------
# TestSalaryCompounding
# ---------------------------------------------------------------------------


class TestSalaryCompounding:
    def test_zero_inflation_and_zero_wage_growth_is_constant(self) -> None:
        """With no growth the salary is the base-year gross every year."""
        cfg = _config(
            inflation_rate="0",
            horizon_years=3,
            salaries=(_salary(gross_annual="60000"),),
        )
        proj = project(cfg)
        for flow in proj.flows:
            assert flow.gross_salary_eur == Decimal("60000.00")

    def test_salary_grows_by_inflation_rate(self) -> None:
        """After 1 year with 2 % inflation: 60000 * 1.02 = 61200."""
        cfg = _config(
            inflation_rate="0.02",
            horizon_years=1,
            salaries=(_salary(gross_annual="60000"),),
        )
        proj = project(cfg)
        assert proj.flows[0].gross_salary_eur == Decimal("61200.00")

    def test_real_wage_growth_compounds_on_top_of_inflation(self) -> None:
        """After 1 year: 60000 * (1 + 0.02 + 0.01) = 60000 * 1.03 = 61800."""
        cfg = _config(
            inflation_rate="0.02",
            horizon_years=1,
            salaries=(_salary(gross_annual="60000", real_wage_growth="0.01"),),
        )
        proj = project(cfg)
        assert proj.flows[0].gross_salary_eur == Decimal("61800.00")

    def test_dkk_salary_converted_to_eur(self) -> None:
        """180 000 DKK * 0.134 = 24 120 EUR at year 0; after 1 year with 0 % inflation = 24120."""
        cfg = _config(
            inflation_rate="0",
            horizon_years=1,
            eur_per_dkk="0.134",
            salaries=(_salary(currency="DKK", gross_annual="180000"),),
        )
        proj = project(cfg)
        assert proj.flows[0].gross_salary_eur == Decimal("24120.00")

    def test_multiple_salary_rules_same_entity_are_summed(self) -> None:
        """Two salaries for same entity: 40k + 20k = 60k (with 0 % inflation)."""
        cfg = _config(
            inflation_rate="0",
            horizon_years=1,
            salaries=(
                _salary(entity="alice", gross_annual="40000"),
                _salary(entity="alice", gross_annual="20000"),
            ),
        )
        proj = project(cfg)
        assert proj.flows[0].gross_salary_eur == Decimal("60000.00")


# ---------------------------------------------------------------------------
# TestContributionRules
# ---------------------------------------------------------------------------


class TestContributionRules:
    def test_indexed_contribution_grows_with_inflation(self) -> None:
        """12000 * 1.02 = 12240 after 1 year."""
        cfg = _config(
            inflation_rate="0.02",
            horizon_years=1,
            contributions=(_contrib(annual="12000", index=True),),
        )
        proj = project(cfg)
        assert proj.flows[0].liquid_contribution_eur == Decimal("12240.00")

    def test_non_indexed_contribution_is_constant(self) -> None:
        """12000 nominal stays 12000 regardless of inflation."""
        cfg = _config(
            inflation_rate="0.05",
            horizon_years=3,
            contributions=(_contrib(annual="12000", index=False),),
        )
        proj = project(cfg)
        for flow in proj.flows:
            assert flow.liquid_contribution_eur == Decimal("12000.00")

    def test_dkk_contribution_converted(self) -> None:
        """180000 DKK * 0.134 = 24120 EUR (0 % inflation, nominal)."""
        cfg = _config(
            inflation_rate="0",
            horizon_years=1,
            eur_per_dkk="0.134",
            contributions=(_contrib(currency="DKK", annual="180000", index=False),),
        )
        proj = project(cfg)
        assert proj.flows[0].liquid_contribution_eur == Decimal("24120.00")

    def test_entity_with_no_contributions_has_zero(self) -> None:
        cfg = _config(
            salaries=(_salary("alice"),),
            contributions=(_contrib("bob", annual="5000"),),
        )
        proj = project(cfg)
        alice_flow = proj.by_entity("alice")[0]
        assert alice_flow.liquid_contribution_eur == Decimal("0.00")


# ---------------------------------------------------------------------------
# TestPensionAccrual
# ---------------------------------------------------------------------------


class TestPensionAccrual:
    def test_dc_fraction_applied_to_gross_salary(self) -> None:
        """21 % of 61200 (1-year 2 % inflation on 60k) = 12852."""
        cfg = _config(
            inflation_rate="0.02",
            horizon_years=1,
            salaries=(_salary(gross_annual="60000"),),
            pension_rules=(_dc_pension(fraction="0.21"),),
        )
        proj = project(cfg)
        assert proj.flows[0].pension_accrual_eur == Decimal("12852.00")

    def test_annual_eur_indexed_grows_with_inflation(self) -> None:
        """2000 * 1.02 = 2040 after 1 year."""
        cfg = _config(
            inflation_rate="0.02",
            horizon_years=1,
            pension_rules=(_annual_pension(annual_eur="2000", index=True),),
        )
        proj = project(cfg)
        assert proj.flows[0].pension_accrual_eur == Decimal("2040.00")

    def test_annual_eur_not_indexed_is_constant(self) -> None:
        """Fixed 2000 EUR stays 2000 regardless of inflation."""
        cfg = _config(
            inflation_rate="0.05",
            horizon_years=3,
            pension_rules=(_annual_pension(annual_eur="2000", index=False),),
        )
        proj = project(cfg)
        for flow in proj.flows:
            assert flow.pension_accrual_eur == Decimal("2000.00")

    def test_cumulative_pension_accumulates(self) -> None:
        """With fixed 2000/year for 3 years: cumulative = 2000, 4000, 6000."""
        cfg = _config(
            inflation_rate="0",
            horizon_years=3,
            pension_rules=(_annual_pension(annual_eur="2000", index=False),),
        )
        proj = project(cfg)
        cumulatives = [f.cumulative_pension_eur for f in proj.flows]
        assert cumulatives == [Decimal("2000.00"), Decimal("4000.00"), Decimal("6000.00")]

    def test_dc_fraction_missing_salary_raises_cashflow_error(self) -> None:
        """A dc_fraction rule with no matching salary entity is an error."""
        cfg = _config(
            salaries=(_salary("alice"),),
            pension_rules=(_dc_pension(entity="bob"),),
        )
        with pytest.raises(CashflowError, match="bob"):
            project(cfg)

    def test_entity_with_no_pension_rule_has_zero_accrual(self) -> None:
        cfg = _config(
            salaries=(_salary("alice"), _salary("bob")),
            pension_rules=(_annual_pension(entity="alice", annual_eur="1000"),),
        )
        proj = project(cfg)
        bob_flow = proj.by_entity("bob")[0]
        assert bob_flow.pension_accrual_eur == Decimal("0.00")
        assert bob_flow.cumulative_pension_eur == Decimal("0.00")


# ---------------------------------------------------------------------------
# TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_horizon_years_must_be_positive(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            _config(horizon_years=0)

    def test_negative_inflation_within_bounds_is_ok(self) -> None:
        cfg = _config(inflation_rate="-0.02", salaries=(_salary(),))
        proj = project(cfg)
        assert len(proj.flows) == cfg.horizon_years

    def test_eur_per_dkk_must_be_positive(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            _config(eur_per_dkk="0")

    def test_salary_gross_must_be_positive(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            _salary(gross_annual="0")

    def test_contribution_annual_must_be_positive(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            _contrib(annual="-100")

    def test_dc_fraction_must_be_in_0_1(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            _dc_pension(fraction="1.5")

    def test_annual_eur_must_be_positive(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            _annual_pension(annual_eur="-500")

    def test_dc_fraction_without_value_raises(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            PensionAccrualRule(kind="dc_fraction", entity="x", vesting_year=2060)

    def test_annual_eur_without_value_raises(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            PensionAccrualRule(kind="annual_eur", entity="x", vesting_year=2060)


# ---------------------------------------------------------------------------
# TestHouseholdScenario — synthetic DK/DE household
# ---------------------------------------------------------------------------


class TestHouseholdScenario:
    """Smoke test with a synthetic two-entity household resembling issue #27."""

    def _household_config(self) -> CashflowConfig:
        return CashflowConfig(
            base_year=2024,
            horizon_years=10,
            inflation_rate=Decimal("0.025"),
            eur_per_dkk=Decimal("0.134"),
            salaries=(
                # Rouven: 800k DKK gross
                SalaryRule(
                    entity="rouven",
                    currency="DKK",
                    gross_annual=Decimal("800000"),
                    real_wage_growth=Decimal("0.01"),
                ),
                # Frau: 70k EUR gross (Beamtin)
                SalaryRule(
                    entity="frau",
                    currency="EUR",
                    gross_annual=Decimal("70000"),
                    real_wage_growth=Decimal("0"),
                ),
            ),
            contributions=(
                # Rouven: 15k DKK/month = 180k DKK/year → Nordnet
                ContributionRule(
                    entity="rouven",
                    currency="DKK",
                    annual=Decimal("180000"),
                    index_to_inflation=True,
                ),
                # Frau: 3.5k EUR/month = 42k EUR/year
                ContributionRule(
                    entity="frau",
                    currency="EUR",
                    annual=Decimal("42000"),
                    index_to_inflation=True,
                ),
            ),
            pension_rules=(
                # PFA 21 % of Rouven's gross salary
                PensionAccrualRule(
                    entity="rouven",
                    kind="dc_fraction",
                    dc_fraction=Decimal("0.21"),
                    vesting_year=2057,
                ),
                # Beamtenpension: synthetic 3k EUR/year accrual for Frau
                PensionAccrualRule(
                    entity="frau",
                    kind="annual_eur",
                    annual_eur=Decimal("3000"),
                    index_accrual_to_inflation=True,
                    vesting_year=2052,
                ),
            ),
        )

    def test_projection_has_correct_shape(self) -> None:
        proj = project(self._household_config())
        assert len(proj.flows) == 20  # 2 entities * 10 years
        assert proj.entities() == ["frau", "rouven"]
        assert proj.years() == list(range(2025, 2035))

    def test_rouven_salary_grows_over_horizon(self) -> None:
        proj = project(self._household_config())
        rouven = proj.by_entity("rouven")
        # Salary should increase every year
        salaries = [f.gross_salary_eur for f in rouven]
        for i in range(1, len(salaries)):
            assert salaries[i] > salaries[i - 1], f"year {i}: salary did not grow"

    def test_frau_cumulative_pension_monotonically_increases(self) -> None:
        proj = project(self._household_config())
        frau = proj.by_entity("frau")
        cumulatives = [f.cumulative_pension_eur for f in frau]
        for i in range(1, len(cumulatives)):
            assert cumulatives[i] > cumulatives[i - 1]

    def test_rouven_dc_pension_fraction_of_salary(self) -> None:
        """DC pension should be ~21 % of gross salary each year."""
        proj = project(self._household_config())
        rouven = proj.by_entity("rouven")
        for flow in rouven:
            ratio = flow.pension_accrual_eur / flow.gross_salary_eur
            assert abs(ratio - Decimal("0.21")) < Decimal(
                "0.001"
            ), f"year {flow.year}: DC ratio {ratio} deviates from 0.21"
