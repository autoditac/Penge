"""Tests for penge.sim.tax — tax overlay."""

from __future__ import annotations

from decimal import Decimal

import pydantic
import pytest

from penge.sim.cashflow import (
    CashflowConfig,
    CashflowProjection,
    ContributionRule,
    PensionAccrualRule,
    SalaryRule,
    project,
)
from penge.sim.tax import (
    DE_DEFAULT,
    DK_DEFAULT,
    EntityTaxRegime,
    TaxConfig,
    apply_tax,
    net_pension_drawdown,
)

# ---------------------------------------------------------------------------
# EntityTaxRegime validation
# ---------------------------------------------------------------------------


class TestEntityTaxRegimeValidation:
    def test_valid_defaults(self) -> None:
        r = EntityTaxRegime(
            salary_income_tax_rate=Decimal("0.42"),
            pension_return_tax_rate=Decimal("0.153"),
            pension_drawdown_tax_rate=Decimal("0.37"),
            capital_gains_effective_rate=Decimal("0.27"),
        )
        assert r.salary_income_tax_rate == Decimal("0.42")

    def test_coerces_from_string(self) -> None:
        r = EntityTaxRegime(
            salary_income_tax_rate="0.42",
            pension_return_tax_rate="0.153",
            pension_drawdown_tax_rate="0.37",
            capital_gains_effective_rate="0.27",
        )
        assert r.pension_return_tax_rate == Decimal("0.153")

    def test_frozen(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            DK_DEFAULT.salary_income_tax_rate = Decimal("0")  # type: ignore[misc]  # intentional mutation to assert frozen-model immutability

    def test_negative_rate_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            EntityTaxRegime(
                salary_income_tax_rate=Decimal("-0.01"),
                pension_return_tax_rate=Decimal("0"),
                pension_drawdown_tax_rate=Decimal("0"),
                capital_gains_effective_rate=Decimal("0"),
            )

    def test_rate_exactly_one_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            EntityTaxRegime(
                salary_income_tax_rate=Decimal("1"),
                pension_return_tax_rate=Decimal("0"),
                pension_drawdown_tax_rate=Decimal("0"),
                capital_gains_effective_rate=Decimal("0"),
            )

    def test_zero_rate_allowed(self) -> None:
        r = EntityTaxRegime(
            salary_income_tax_rate=Decimal("0"),
            pension_return_tax_rate=Decimal("0"),
            pension_drawdown_tax_rate=Decimal("0"),
            capital_gains_effective_rate=Decimal("0"),
        )
        assert r.salary_income_tax_rate == Decimal("0")


# ---------------------------------------------------------------------------
# Default regimes sanity
# ---------------------------------------------------------------------------


class TestDefaultRegimes:
    def test_dk_default_rates(self) -> None:
        assert DK_DEFAULT.salary_income_tax_rate == Decimal("0.42")
        assert DK_DEFAULT.pension_return_tax_rate == Decimal("0.153")
        assert DK_DEFAULT.pension_drawdown_tax_rate == Decimal("0.37")
        assert DK_DEFAULT.capital_gains_effective_rate == Decimal("0.27")

    def test_de_default_rates(self) -> None:
        assert DE_DEFAULT.salary_income_tax_rate == Decimal("0.33")
        assert DE_DEFAULT.pension_return_tax_rate == Decimal("0")
        assert DE_DEFAULT.pension_drawdown_tax_rate == Decimal("0.33")


# ---------------------------------------------------------------------------
# TaxConfig
# ---------------------------------------------------------------------------


class TestTaxConfig:
    def test_defaults(self) -> None:
        tc = TaxConfig()
        assert tc.enabled is True
        assert tc.regimes == {}

    def test_disabled(self) -> None:
        tc = TaxConfig(enabled=False)
        assert tc.enabled is False

    def test_frozen(self) -> None:
        tc = TaxConfig()
        with pytest.raises(pydantic.ValidationError):
            tc.enabled = False  # type: ignore[misc]  # intentional mutation to assert frozen-model immutability


# ---------------------------------------------------------------------------
# apply_tax — gross mode
# ---------------------------------------------------------------------------


class TestApplyTaxDisabled:
    def _projection(self) -> CashflowProjection:
        cfg = CashflowConfig(
            base_year=2024,
            horizon_years=3,
            inflation_rate=Decimal("0.02"),
            eur_per_dkk=Decimal("0.134"),
            salaries=(
                SalaryRule(
                    entity="alice",
                    gross_annual=Decimal("100000"),
                    currency="EUR",
                    real_wage_growth=Decimal("0"),
                ),
            ),
            contributions=(),
            pension_rules=(
                PensionAccrualRule(
                    entity="alice",
                    kind="annual_eur",
                    annual_eur=Decimal("5000"),
                    index_accrual_to_inflation=False,
                    vesting_year=2030,
                ),
            ),
        )
        return project(cfg)

    def test_disabled_returns_same_projection(self) -> None:
        proj = self._projection()
        tc = TaxConfig(enabled=False, regimes={"alice": DK_DEFAULT})
        result = apply_tax(proj, tc)
        assert result is proj

    def test_no_regimes_returns_unchanged_flows(self) -> None:
        proj = self._projection()
        tc = TaxConfig(enabled=True, regimes={})
        result = apply_tax(proj, tc)
        assert result.flows == proj.flows


# ---------------------------------------------------------------------------
# apply_tax — salary netting
# ---------------------------------------------------------------------------


def _make_config(
    entity: str = "alice",
    gross_annual: str = "100000",
    pension_annual: str = "5000",
    horizon: int = 3,
) -> CashflowConfig:
    return CashflowConfig(
        base_year=2024,
        horizon_years=horizon,
        inflation_rate=Decimal("0"),  # no inflation — easier maths
        eur_per_dkk=Decimal("0.134"),
        salaries=(
            SalaryRule(
                entity=entity,
                gross_annual=Decimal(gross_annual),
                currency="EUR",
                real_wage_growth=Decimal("0"),
            ),
        ),
        contributions=(
            ContributionRule(
                entity=entity,
                annual=Decimal("12000"),
                currency="EUR",
                index_to_inflation=False,
            ),
        ),
        pension_rules=(
            PensionAccrualRule(
                entity=entity,
                kind="annual_eur",
                annual_eur=Decimal(pension_annual),
                index_accrual_to_inflation=False,
                vesting_year=2030,
            ),
        ),
    )


class TestApplyTaxSalary:
    def test_net_salary_calculation(self) -> None:
        """Net salary = gross * (1 - 0.42) = 58 000."""
        cfg = _make_config(gross_annual="100000", horizon=1)
        proj = project(cfg)
        tc = TaxConfig(regimes={"alice": DK_DEFAULT})
        net = apply_tax(proj, tc)
        flow = net.flows[0]
        assert flow.entity == "alice"
        # 100_000 * (1 - 0.42) = 58_000.00
        assert flow.gross_salary_eur == Decimal("58000.00")

    def test_liquid_contribution_unchanged(self) -> None:
        """Liquid contributions are NOT modified by apply_tax."""
        cfg = _make_config(horizon=1)
        proj = project(cfg)
        tc = TaxConfig(regimes={"alice": DK_DEFAULT})
        net = apply_tax(proj, tc)
        assert net.flows[0].liquid_contribution_eur == proj.flows[0].liquid_contribution_eur

    def test_config_preserved(self) -> None:
        """The CashflowConfig embedded in the net projection is unchanged."""
        cfg = _make_config(horizon=1)
        proj = project(cfg)
        tc = TaxConfig(regimes={"alice": DK_DEFAULT})
        net = apply_tax(proj, tc)
        assert net.config is proj.config


# ---------------------------------------------------------------------------
# apply_tax — pension netting
# ---------------------------------------------------------------------------


class TestApplyTaxPension:
    def test_pension_accrual_netted_by_return_tax(self) -> None:
        """DK: pension_accrual *= (1 - 0.153) = 4 235.00 from 5 000."""
        cfg = _make_config(pension_annual="5000", horizon=1)
        proj = project(cfg)
        tc = TaxConfig(regimes={"alice": DK_DEFAULT})
        net = apply_tax(proj, tc)
        # 5_000 * (1 - 0.153) = 4_235.00
        assert net.flows[0].pension_accrual_eur == Decimal("4235.00")

    def test_pension_cumulative_adjusted_by_accrual_delta(self) -> None:
        """Cumulative pension reflects the full balance adjusted by the accrual delta.

        With no opening balance and no growth rate, cumulative_eur (gross) grows
        as 5000, 10000, 15000.  After applying pension_return_tax_rate=0.153 the
        accrual becomes 4235 each year; the cumulative is adjusted by the delta
        (original_cumulative - original_accrual + net_accrual):
          Year 1: 5000 - 5000 + 4235 = 4235
          Year 2: 10000 - 5000 + 4235 = 9235
          Year 3: 15000 - 5000 + 4235 = 14235
        """
        cfg = _make_config(pension_annual="5000", horizon=3)
        proj = project(cfg)
        tc = TaxConfig(regimes={"alice": DK_DEFAULT})
        net = apply_tax(proj, tc)
        cumulatives = [f.cumulative_pension_eur for f in net.flows]
        assert cumulatives == [Decimal("4235.00"), Decimal("9235.00"), Decimal("14235.00")]

    def test_zero_pension_return_tax_de(self) -> None:
        """DE default has pension_return_tax_rate=0, so accrual is unchanged."""
        cfg = _make_config(entity="frau", pension_annual="5000", horizon=1)
        proj = project(cfg)
        tc = TaxConfig(regimes={"frau": DE_DEFAULT})
        net = apply_tax(proj, tc)
        # 5_000 * (1 - 0) = 5_000.00
        assert net.flows[0].pension_accrual_eur == Decimal("5000.00")


# ---------------------------------------------------------------------------
# apply_tax — multi-entity
# ---------------------------------------------------------------------------


class TestApplyTaxMultiEntity:
    def _two_entity_config(self) -> CashflowConfig:
        return CashflowConfig(
            base_year=2024,
            horizon_years=1,
            inflation_rate=Decimal("0"),
            eur_per_dkk=Decimal("0.134"),
            salaries=(
                SalaryRule(
                    entity="rouven",
                    gross_annual=Decimal("100000"),
                    currency="EUR",
                    real_wage_growth=Decimal("0"),
                ),
                SalaryRule(
                    entity="frau",
                    gross_annual=Decimal("80000"),
                    currency="EUR",
                    real_wage_growth=Decimal("0"),
                ),
            ),
            contributions=(),
            pension_rules=(),
        )

    def test_per_entity_rates_applied(self) -> None:
        cfg = self._two_entity_config()
        proj = project(cfg)
        tc = TaxConfig(regimes={"rouven": DK_DEFAULT, "frau": DE_DEFAULT})
        net = apply_tax(proj, tc)
        flows = {f.entity: f for f in net.flows}
        # rouven: 100_000 * (1 - 0.42) = 58_000
        assert flows["rouven"].gross_salary_eur == Decimal("58000.00")
        # frau: 80_000 * (1 - 0.33) = 53_600
        assert flows["frau"].gross_salary_eur == Decimal("53600.00")

    def test_entity_without_regime_unchanged(self) -> None:
        """Entity not in regimes dict is passed through with no modification."""
        cfg = self._two_entity_config()
        proj = project(cfg)
        tc = TaxConfig(regimes={"rouven": DK_DEFAULT})  # frau has no regime
        net = apply_tax(proj, tc)
        flows = {f.entity: f for f in net.flows}
        # frau: unchanged
        assert flows["frau"].gross_salary_eur == Decimal("80000.00")


# ---------------------------------------------------------------------------
# net_pension_drawdown
# ---------------------------------------------------------------------------


class TestNetPensionDrawdown:
    def test_dk_drawdown_rate(self) -> None:
        """DK: 30_000 * (1 - 0.37) = 18_900."""
        tc = TaxConfig(regimes={"rouven": DK_DEFAULT})
        result = net_pension_drawdown(Decimal("30000"), "rouven", tc)
        assert result == Decimal("18900.00")

    def test_de_drawdown_rate(self) -> None:
        """DE: 20_000 * (1 - 0.33) = 13_400."""
        tc = TaxConfig(regimes={"frau": DE_DEFAULT})
        result = net_pension_drawdown(Decimal("20000"), "frau", tc)
        assert result == Decimal("13400.00")

    def test_disabled_returns_gross(self) -> None:
        tc = TaxConfig(enabled=False, regimes={"rouven": DK_DEFAULT})
        result = net_pension_drawdown(Decimal("30000"), "rouven", tc)
        assert result == Decimal("30000")

    def test_entity_without_regime_returns_gross(self) -> None:
        tc = TaxConfig(regimes={})
        result = net_pension_drawdown(Decimal("30000"), "unknown", tc)
        assert result == Decimal("30000")

    def test_zero_rate(self) -> None:
        zero_regime = EntityTaxRegime(
            salary_income_tax_rate=Decimal("0"),
            pension_return_tax_rate=Decimal("0"),
            pension_drawdown_tax_rate=Decimal("0"),
            capital_gains_effective_rate=Decimal("0"),
        )
        tc = TaxConfig(regimes={"alice": zero_regime})
        result = net_pension_drawdown(Decimal("10000"), "alice", tc)
        assert result == Decimal("10000.00")
