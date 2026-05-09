"""Tests for penge.sim.scenario — scenario engine."""

from __future__ import annotations

import json
import random as _random
from decimal import Decimal

import pytest
from pydantic import ValidationError

from penge.sim.cashflow import (
    CashflowConfig,
    SalaryRule,
    project,
)
from penge.sim.goal import GoalConfig
from penge.sim.montecarlo import MonteCarloConfig
from penge.sim.returns import BootstrapReturnModel
from penge.sim.scenario import (
    HousePurchaseScenario,
    ScenarioComparison,
    ScenarioError,
    WorkReductionScenario,
    compare,
)
from penge.sim.tax import TaxConfig

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_rng = _random.Random(99999)  # noqa: S311
_MONTHLY_RETURNS = [Decimal(str(round(_rng.gauss(0.006, 0.04), 6))) for _ in range(360)]


def _return_model(seed: int = 42) -> BootstrapReturnModel:
    return BootstrapReturnModel(
        asset_returns={"equity": _MONTHLY_RETURNS},
        inflation={"dk": [Decimal("0.002")] * 360},
        block_months=12,
        seed=seed,
    )


def _cashflow_cfg(
    entity: str = "person_dk",
    gross_annual: Decimal = Decimal("80000"),
    horizon: int = 10,
    base_year: int = 2024,
) -> CashflowConfig:
    return CashflowConfig(
        base_year=base_year,
        horizon_years=horizon,
        inflation_rate=Decimal("0.02"),
        eur_per_dkk=Decimal("0.134"),
        salaries=(
            SalaryRule(
                entity=entity,
                gross_annual=gross_annual,
                currency="EUR",
            ),
        ),
        contributions=(),
        pension_rules=(),
    )


def _mc_cfg(
    portfolio: Decimal = Decimal("200000"),
    n_paths: int = 100,
) -> MonteCarloConfig:
    return MonteCarloConfig(
        n_paths=n_paths,
        asset_weights={"equity": Decimal("1")},
        initial_portfolio_eur=portfolio,
    )


def _goal(annual: Decimal = Decimal("50000")) -> GoalConfig:
    return GoalConfig(target_annual_eur=annual)


# ---------------------------------------------------------------------------
# HousePurchaseScenario
# ---------------------------------------------------------------------------


class TestHousePurchaseScenario:
    def test_annual_payment_no_interest(self) -> None:
        s = HousePurchaseScenario(
            year=2026,
            price_eur=Decimal("300000"),
            downpayment_eur=Decimal("60000"),
            mortgage_rate=Decimal("0"),
            term_years=20,
        )
        assert s.annual_payment_eur() == Decimal("12000.00")

    def test_annual_payment_with_interest_sanity(self) -> None:
        s = HousePurchaseScenario(
            year=2026,
            price_eur=Decimal("300000"),
            downpayment_eur=Decimal("60000"),
            mortgage_rate=Decimal("0.03"),
            term_years=25,
        )
        p = s.annual_payment_eur()
        principal = Decimal("240000")
        assert principal / 25 < p < 2 * principal / 25

    def test_full_cash_purchase_zero_payment(self) -> None:
        s = HousePurchaseScenario(
            year=2027,
            price_eur=Decimal("150000"),
            downpayment_eur=Decimal("150000"),
            mortgage_rate=Decimal("0.02"),
            term_years=10,
        )
        assert s.annual_payment_eur() == Decimal("0")

    def test_downpayment_exceeds_price_raises(self) -> None:
        with pytest.raises(ValidationError):
            HousePurchaseScenario(
                year=2027,
                price_eur=Decimal("100000"),
                downpayment_eur=Decimal("150000"),
                mortgage_rate=Decimal("0.02"),
                term_years=10,
            )

    def test_apply_reduces_portfolio(self) -> None:
        s = HousePurchaseScenario(
            year=2026,
            price_eur=Decimal("300000"),
            downpayment_eur=Decimal("50000"),
            mortgage_rate=Decimal("0"),
            term_years=20,
        )
        proj = project(_cashflow_cfg())
        mc = _mc_cfg(portfolio=Decimal("200000"))
        _, new_mc = s.apply(proj, mc)
        assert new_mc.initial_portfolio_eur == Decimal("150000")

    def test_apply_reduces_liquid_contribution_in_mortgage_years(self) -> None:
        s = HousePurchaseScenario(
            year=2026,
            price_eur=Decimal("300000"),
            downpayment_eur=Decimal("60000"),
            mortgage_rate=Decimal("0"),
            term_years=5,
        )
        proj = project(_cashflow_cfg(base_year=2024, horizon=10))
        mc = _mc_cfg()
        new_proj, _ = s.apply(proj, mc)
        first_entity = new_proj.entities()[0]

        payment = s.annual_payment_eur()
        for flow in new_proj.flows:
            if flow.entity == first_entity and 2026 <= flow.year <= 2030:
                orig = next(
                    f for f in proj.flows if f.entity == flow.entity and f.year == flow.year
                )
                assert flow.liquid_contribution_eur == orig.liquid_contribution_eur - payment
            elif flow.entity == first_entity:
                orig = next(
                    f for f in proj.flows if f.entity == flow.entity and f.year == flow.year
                )
                assert flow.liquid_contribution_eur == orig.liquid_contribution_eur

    def test_apply_is_immutable(self) -> None:
        """Original proj and mc_cfg must not be mutated."""
        s = HousePurchaseScenario(
            year=2026,
            price_eur=Decimal("300000"),
            downpayment_eur=Decimal("60000"),
            mortgage_rate=Decimal("0.02"),
            term_years=10,
        )
        proj = project(_cashflow_cfg())
        mc = _mc_cfg(portfolio=Decimal("200000"))
        s.apply(proj, mc)
        assert mc.initial_portfolio_eur == Decimal("200000")


# ---------------------------------------------------------------------------
# WorkReductionScenario
# ---------------------------------------------------------------------------


class TestWorkReductionScenario:
    def test_salary_scaled_from_reduction_year(self) -> None:
        s = WorkReductionScenario(
            entity="person_dk",
            year=2028,
            fte_fraction=Decimal("0.8"),
        )
        proj = project(_cashflow_cfg(base_year=2024, horizon=10, gross_annual=Decimal("90000")))
        new_proj, _ = s.apply(proj, _mc_cfg())

        for flow in new_proj.flows:
            if flow.entity == "person_dk" and flow.year >= 2028:
                orig = next(
                    f for f in proj.flows if f.entity == "person_dk" and f.year == flow.year
                )
                # Should be scaled down to approximately 80%
                assert flow.gross_salary_eur < orig.gross_salary_eur

    def test_salary_before_reduction_year_unchanged(self) -> None:
        s = WorkReductionScenario(
            entity="person_dk",
            year=2028,
            fte_fraction=Decimal("0.8"),
        )
        proj = project(_cashflow_cfg(base_year=2024, horizon=10, gross_annual=Decimal("90000")))
        new_proj, _ = s.apply(proj, _mc_cfg())

        for flow in new_proj.flows:
            if flow.entity == "person_dk" and flow.year < 2028:
                orig = next(
                    f for f in proj.flows if f.entity == "person_dk" and f.year == flow.year
                )
                assert flow.gross_salary_eur == orig.gross_salary_eur

    def test_cumulative_pension_recomputed(self) -> None:
        s = WorkReductionScenario(
            entity="person_dk",
            year=2027,
            fte_fraction=Decimal("0.5"),
        )
        proj = project(_cashflow_cfg(base_year=2024, horizon=8))
        new_proj, _ = s.apply(proj, _mc_cfg())

        # cumulative_pension should be monotonically increasing
        entity_flows = sorted(
            [f for f in new_proj.flows if f.entity == "person_dk"], key=lambda f: f.year
        )
        for i in range(1, len(entity_flows)):
            assert (
                entity_flows[i].cumulative_pension_eur >= entity_flows[i - 1].cumulative_pension_eur
            )

    def test_mc_cfg_unchanged_by_work_reduction(self) -> None:
        s = WorkReductionScenario(entity="person_dk", year=2027, fte_fraction=Decimal("0.8"))
        proj = project(_cashflow_cfg())
        mc = _mc_cfg(portfolio=Decimal("150000"))
        _, new_mc = s.apply(proj, mc)
        assert new_mc.initial_portfolio_eur == Decimal("150000")

    def test_fte_above_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            WorkReductionScenario(entity="person_dk", year=2026, fte_fraction=Decimal("1.1"))

    def test_fte_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            WorkReductionScenario(entity="person_dk", year=2026, fte_fraction=Decimal("0"))


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------


class TestCompare:
    def test_compare_returns_baseline_and_scenarios(self) -> None:
        result = compare(
            _cashflow_cfg(),
            TaxConfig(),
            _goal(),
            _return_model(),
            _mc_cfg(n_paths=50),
            {
                "work_reduction": WorkReductionScenario(
                    entity="person_dk",
                    year=2027,
                    fte_fraction=Decimal("0.8"),
                ),
                "house_purchase": HousePurchaseScenario(
                    year=2026,
                    price_eur=Decimal("300000"),
                    downpayment_eur=Decimal("60000"),
                    mortgage_rate=Decimal("0.02"),
                    term_years=20,
                ),
            },
        )
        assert isinstance(result, ScenarioComparison)
        assert len(result.scenarios) == 2
        assert result.scenarios[0].name == "work_reduction"
        assert result.scenarios[1].name == "house_purchase"

    def test_baseline_p_goal_met_in_range(self) -> None:
        result = compare(
            _cashflow_cfg(),
            TaxConfig(),
            _goal(),
            _return_model(),
            _mc_cfg(n_paths=50),
            {},
        )
        assert Decimal("0") <= result.baseline.p_goal_met <= Decimal("1")

    def test_to_json_valid(self) -> None:
        result = compare(
            _cashflow_cfg(),
            TaxConfig(),
            _goal(),
            _return_model(),
            _mc_cfg(n_paths=50),
            {
                "fte80": WorkReductionScenario(
                    entity="person_dk",
                    year=2027,
                    fte_fraction=Decimal("0.8"),
                )
            },
        )
        js = result.to_json()
        data = json.loads(js)
        assert "baseline" in data
        assert "scenarios" in data
        assert data["scenarios"][0]["name"] == "fte80"

    def test_to_markdown_contains_headers(self) -> None:
        result = compare(
            _cashflow_cfg(),
            TaxConfig(),
            _goal(),
            _return_model(),
            _mc_cfg(n_paths=50),
            {
                "fte80": WorkReductionScenario(
                    entity="person_dk",
                    year=2027,
                    fte_fraction=Decimal("0.8"),
                )
            },
        )
        md = result.to_markdown()
        assert "# Scenario Comparison" in md
        assert "fte80" in md
        assert "P(goal met)" in md

    def test_empty_scenarios_dict(self) -> None:
        result = compare(
            _cashflow_cfg(),
            TaxConfig(),
            _goal(),
            _return_model(),
            _mc_cfg(n_paths=50),
            {},
        )
        assert len(result.scenarios) == 0

    def test_negative_portfolio_from_downpayment_raises(self) -> None:
        s = HousePurchaseScenario(
            year=2025,
            price_eur=Decimal("500000"),
            downpayment_eur=Decimal("300000"),
            mortgage_rate=Decimal("0.02"),
            term_years=20,
        )
        with pytest.raises(ScenarioError, match="negative"):
            compare(
                _cashflow_cfg(),
                TaxConfig(),
                _goal(),
                _return_model(),
                _mc_cfg(portfolio=Decimal("100000"), n_paths=50),
                {"expensive_house": s},
            )

    def test_house_purchase_reduces_portfolio_at_least_by_downpayment(self) -> None:
        """A house purchase should reduce the effective starting portfolio."""
        cfg = _cashflow_cfg(horizon=10)
        mc = _mc_cfg(portfolio=Decimal("300000"), n_paths=200)
        house = HousePurchaseScenario(
            year=2025,
            price_eur=Decimal("400000"),
            downpayment_eur=Decimal("150000"),
            mortgage_rate=Decimal("0.03"),
            term_years=20,
        )
        proj = project(cfg)
        new_proj, new_mc = house.apply(proj, mc)
        assert new_mc.initial_portfolio_eur == mc.initial_portfolio_eur - Decimal("150000")
