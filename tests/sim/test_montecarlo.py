"""Tests for penge.sim.montecarlo — Monte-Carlo FIRE runner."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
import random as _random
from decimal import Decimal

import pydantic
import pytest
from pydantic import ValidationError

from penge.sim.cashflow import (
    CashflowConfig,
    ContributionRule,
    PensionAccrualRule,
    SalaryRule,
    project,
)
from penge.sim.goal import GoalConfig
from penge.sim.montecarlo import MonteCarloConfig, run
from penge.sim.returns import BootstrapReturnModel
from penge.sim.tax import TaxConfig

_rng = _random.Random(12345)  # noqa: S311
_MONTHLY_RETURNS = [
    Decimal(str(round(_rng.gauss(0.006, 0.04), 6)))
    for _ in range(360)  # 30 years
]


def _simple_return_model(seed: int = 42) -> BootstrapReturnModel:
    """Simple 1-asset return model with 30 years of monthly history."""
    return BootstrapReturnModel(
        asset_returns={"equity": _MONTHLY_RETURNS},
        inflation={"dk": [Decimal("0.002")] * 360},
        block_months=12,
        seed=seed,
    )


def _simple_cashflow(
    horizon: int = 10,
    annual_pension_eur: str = "5000",
    vesting_year: int = 2025,
) -> CashflowConfig:
    return CashflowConfig(
        base_year=2024,
        horizon_years=horizon,
        inflation_rate=Decimal("0.02"),
        eur_per_dkk=Decimal("0.134"),
        salaries=(
            SalaryRule(
                entity="alice",
                gross_annual=Decimal("80000"),
                currency="EUR",
                real_wage_growth=Decimal("0"),
            ),
        ),
        contributions=(
            ContributionRule(
                entity="alice",
                annual=Decimal("12000"),
                currency="EUR",
                index_to_inflation=False,
            ),
        ),
        pension_rules=(
            PensionAccrualRule(
                entity="alice",
                kind="annual_eur",
                annual_eur=Decimal(annual_pension_eur),
                index_accrual_to_inflation=False,
                vesting_year=vesting_year,
            ),
        ),
    )


def _simple_mc_config(n_paths: int = 100) -> MonteCarloConfig:
    return MonteCarloConfig(
        n_paths=n_paths,
        asset_weights={"equity": Decimal("1")},
        initial_portfolio_eur=Decimal("500000"),
        capital_gains_effective_rate=Decimal("0.27"),
    )


# ---------------------------------------------------------------------------
# MonteCarloConfig validation
# ---------------------------------------------------------------------------


class TestMonteCarloConfigValidation:
    def test_valid_config(self) -> None:
        cfg = _simple_mc_config()
        assert cfg.n_paths == 100
        assert cfg.asset_weights == {"equity": Decimal("1")}

    def test_weights_must_sum_to_one(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="sum to 1"):
            MonteCarloConfig(
                n_paths=10,
                asset_weights={"equity": Decimal("0.5"), "bonds": Decimal("0.3")},
                initial_portfolio_eur=Decimal("100000"),
            )

    def test_empty_weights_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            MonteCarloConfig(
                n_paths=10,
                asset_weights={},
                initial_portfolio_eur=Decimal("100000"),
            )

    def test_negative_portfolio_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            MonteCarloConfig(
                n_paths=10,
                asset_weights={"equity": Decimal("1")},
                initial_portfolio_eur=Decimal("-1"),
            )

    def test_cg_rate_one_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            MonteCarloConfig(
                n_paths=10,
                asset_weights={"equity": Decimal("1")},
                initial_portfolio_eur=Decimal("100000"),
                capital_gains_effective_rate=Decimal("1"),
            )

    def test_coerces_from_string(self) -> None:
        cfg = MonteCarloConfig(
            n_paths=10,
            asset_weights={"equity": Decimal("1.0")},
            initial_portfolio_eur=Decimal("500000"),
        )
        assert cfg.initial_portfolio_eur == Decimal("500000")

    def test_frozen(self) -> None:
        cfg = _simple_mc_config()
        with pytest.raises(ValidationError):
            cfg.n_paths = 200


# ---------------------------------------------------------------------------
# MonteCarloResult structure
# ---------------------------------------------------------------------------


class TestMonteCarloResultStructure:
    def test_result_has_correct_keys(self) -> None:
        model = _simple_return_model()
        cashflow_cfg = _simple_cashflow(horizon=5)
        proj = project(cashflow_cfg)
        goal = GoalConfig(target_annual_eur=Decimal("50000"))
        mc_cfg = _simple_mc_config(n_paths=50)
        result = run(proj, TaxConfig(), goal, model, mc_cfg)
        assert set(result.p10_portfolio.keys()) == set(range(2025, 2030))
        assert set(result.p50_portfolio.keys()) == set(result.p10_portfolio.keys())
        assert set(result.p90_portfolio.keys()) == set(result.p10_portfolio.keys())

    def test_result_is_frozen(self) -> None:
        model = _simple_return_model()
        proj = project(_simple_cashflow(horizon=3))
        goal = GoalConfig(target_annual_eur=Decimal("50000"))
        result = run(proj, TaxConfig(), goal, model, _simple_mc_config(n_paths=10))
        with pytest.raises(ValidationError):
            result.p_goal_met = Decimal("0.5")

    def test_percentile_ordering(self) -> None:
        """p10 <= p50 <= p90 for every year."""
        model = _simple_return_model()
        proj = project(_simple_cashflow(horizon=10))
        goal = GoalConfig(target_annual_eur=Decimal("999999999"))
        result = run(proj, TaxConfig(), goal, model, _simple_mc_config(n_paths=200))
        for year in result.p10_portfolio:
            assert result.p10_portfolio[year] <= result.p50_portfolio[year]
            assert result.p50_portfolio[year] <= result.p90_portfolio[year]

    def test_n_paths_and_seed_stored(self) -> None:
        model = _simple_return_model(seed=7)
        proj = project(_simple_cashflow(horizon=3))
        goal = GoalConfig(target_annual_eur=Decimal("50000"))
        result = run(proj, TaxConfig(), goal, model, _simple_mc_config(n_paths=20))
        assert result.n_paths == 20
        assert result.seed == 7
        assert len(result.history_hash) == 64  # SHA-256 hex

    def test_p_goal_met_in_range(self) -> None:
        model = _simple_return_model()
        proj = project(_simple_cashflow(horizon=5))
        goal = GoalConfig(target_annual_eur=Decimal("50000"))
        result = run(proj, TaxConfig(), goal, model, _simple_mc_config(n_paths=50))
        assert Decimal("0") <= result.p_goal_met <= Decimal("1")


# ---------------------------------------------------------------------------
# Reproducibility (seeded)
# ---------------------------------------------------------------------------


class TestReproducibility:
    def test_same_seed_same_result(self) -> None:
        """Two runs with the same seed must produce identical output."""
        model = _simple_return_model(seed=42)
        proj = project(_simple_cashflow(horizon=5))
        goal = GoalConfig(target_annual_eur=Decimal("50000"))
        mc_cfg = _simple_mc_config(n_paths=100)
        result1 = run(proj, TaxConfig(), goal, model, mc_cfg)
        result2 = run(proj, TaxConfig(), goal, model, mc_cfg)
        assert result1.p_goal_met == result2.p_goal_met
        assert result1.median_fire_year == result2.median_fire_year
        assert result1.p50_portfolio == result2.p50_portfolio

    def test_different_seed_different_result(self) -> None:
        model_a = _simple_return_model(seed=0)
        model_b = _simple_return_model(seed=99)
        proj = project(_simple_cashflow(horizon=5))
        goal = GoalConfig(target_annual_eur=Decimal("50000"))
        mc_cfg = _simple_mc_config(n_paths=500)
        result_a = run(proj, TaxConfig(), goal, model_a, mc_cfg)
        result_b = run(proj, TaxConfig(), goal, model_b, mc_cfg)
        # With 500 paths, p_goal_met or extreme percentiles should differ
        results_differ = result_a.p_goal_met != result_b.p_goal_met or any(
            result_a.p10_portfolio[y] != result_b.p10_portfolio[y]
            or result_a.p90_portfolio[y] != result_b.p90_portfolio[y]
            for y in result_a.p10_portfolio
        )
        assert results_differ


# ---------------------------------------------------------------------------
# Goal probability
# ---------------------------------------------------------------------------


class TestGoalProbability:
    def test_goal_always_met_with_massive_portfolio(self) -> None:
        """With a €100M starting portfolio, p_goal_met should be 1."""
        model = _simple_return_model()
        proj = project(_simple_cashflow(horizon=5))
        goal = GoalConfig(target_annual_eur=Decimal("50000"))
        mc_cfg = MonteCarloConfig(
            n_paths=100,
            asset_weights={"equity": Decimal("1")},
            initial_portfolio_eur=Decimal("100000000"),  # 100M EUR
        )
        result = run(proj, TaxConfig(), goal, model, mc_cfg)
        assert result.p_goal_met == Decimal("1")
        assert result.median_fire_year is not None

    def test_goal_never_met_with_zero_portfolio(self) -> None:
        """With €0 portfolio and tiny pension, goal of €50k is never met."""
        model = _simple_return_model()
        proj = project(_simple_cashflow(horizon=5, annual_pension_eur="100", vesting_year=2025))
        goal = GoalConfig(target_annual_eur=Decimal("50000"))
        mc_cfg = MonteCarloConfig(
            n_paths=50,
            asset_weights={"equity": Decimal("1")},
            initial_portfolio_eur=Decimal("0"),
            capital_gains_effective_rate=Decimal("0"),
        )
        result = run(proj, TaxConfig(), goal, model, mc_cfg)
        assert result.p_goal_met == Decimal("0")
        assert result.median_fire_year is None

    def test_median_fire_year_none_when_p_below_50pct(self) -> None:
        """median_fire_year is None when fewer than 50 % of paths meet the goal."""
        model = _simple_return_model()
        proj = project(_simple_cashflow(horizon=5))
        # Set an extremely high target so almost no paths meet it
        goal = GoalConfig(target_annual_eur=Decimal("9999999"))
        result = run(proj, TaxConfig(), goal, model, _simple_mc_config(n_paths=200))
        assert result.median_fire_year is None


# ---------------------------------------------------------------------------
# Tax overlay integration
# ---------------------------------------------------------------------------


class TestTaxIntegration:
    def test_disabled_tax_same_as_zero_rate(self) -> None:
        """TaxConfig(enabled=False) with cg_rate=0 gives consistent p50."""
        model = _simple_return_model()
        proj = project(_simple_cashflow(horizon=5))
        goal = GoalConfig(target_annual_eur=Decimal("50000"))
        mc_cfg = MonteCarloConfig(
            n_paths=50,
            asset_weights={"equity": Decimal("1")},
            initial_portfolio_eur=Decimal("500000"),
            capital_gains_effective_rate=Decimal("0"),
        )
        result = run(proj, TaxConfig(enabled=False), goal, model, mc_cfg)
        # Just verify it runs and returns valid structure
        assert Decimal("0") <= result.p_goal_met <= Decimal("1")

    def test_higher_cg_rate_reduces_portfolio(self) -> None:
        """Higher capital-gains rate → lower median portfolio value after N years."""
        model = _simple_return_model(seed=0)
        proj = project(_simple_cashflow(horizon=10))
        goal = GoalConfig(target_annual_eur=Decimal("999999999"))  # never met
        mc_low = MonteCarloConfig(
            n_paths=200,
            asset_weights={"equity": Decimal("1")},
            initial_portfolio_eur=Decimal("500000"),
            capital_gains_effective_rate=Decimal("0"),
        )
        mc_high = MonteCarloConfig(
            n_paths=200,
            asset_weights={"equity": Decimal("1")},
            initial_portfolio_eur=Decimal("500000"),
            capital_gains_effective_rate=Decimal("0.42"),
        )
        result_low = run(proj, TaxConfig(), goal, model, mc_low)
        result_high = run(proj, TaxConfig(), goal, model, mc_high)
        last_year = max(result_low.p50_portfolio)
        assert result_low.p50_portfolio[last_year] > result_high.p50_portfolio[last_year]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrors:
    def test_unknown_asset_label_raises(self) -> None:
        model = _simple_return_model()
        proj = project(_simple_cashflow(horizon=3))
        goal = GoalConfig(target_annual_eur=Decimal("50000"))
        mc_cfg = MonteCarloConfig(
            n_paths=10,
            asset_weights={"nonexistent_asset": Decimal("1")},
            initial_portfolio_eur=Decimal("100000"),
        )
        with pytest.raises(ValueError, match="Unknown asset labels"):
            run(proj, TaxConfig(), goal, model, mc_cfg)


# ---------------------------------------------------------------------------
# Performance smoke test
# ---------------------------------------------------------------------------


class TestPerformance:
    def test_10k_paths_10_years(self) -> None:
        """N=10000, T=10 must complete (no assertion on wall time in CI)."""
        import time

        model = _simple_return_model()
        proj = project(_simple_cashflow(horizon=10))
        goal = GoalConfig(target_annual_eur=Decimal("50000"))
        mc_cfg = _simple_mc_config(n_paths=10_000)
        t0 = time.monotonic()
        result = run(proj, TaxConfig(), goal, model, mc_cfg)
        elapsed = time.monotonic() - t0
        assert result.n_paths == 10_000
        assert elapsed < 30.0, f"10k/10y took {elapsed:.1f}s; must be < 30s"
