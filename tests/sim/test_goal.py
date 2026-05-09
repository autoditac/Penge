"""Tests for penge.sim.goal — FIRE goal evaluation."""

from __future__ import annotations

from decimal import Decimal

import pydantic
import pytest

from penge.sim.cashflow import (
    CashflowConfig,
    ContributionRule,
    PensionAccrualRule,
    SalaryRule,
    project,
)
from penge.sim.goal import GoalConfig, evaluate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _simple_config(
    *,
    horizon: int = 20,
    base_year: int = 2024,
    annual_pension_eur: Decimal | None = None,
    vesting_year: int = 2030,
) -> CashflowConfig:
    """Minimal CashflowConfig with one entity 'alice'."""
    pension_rules: list[PensionAccrualRule] = []
    if annual_pension_eur is not None:
        pension_rules.append(
            PensionAccrualRule(
                entity="alice",
                kind="annual_eur",
                annual_eur=annual_pension_eur,
                index_accrual_to_inflation=False,
                vesting_year=vesting_year,
            )
        )
    return CashflowConfig(
        base_year=base_year,
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
                index_to_inflation=False,
            ),
        ),
        pension_rules=tuple(pension_rules),
    )


def _portfolio_by_year(
    base_year: int,
    horizon: int,
    annual_value: Decimal,
) -> list[tuple[int, Decimal]]:
    """Constant portfolio value across all projected years."""
    return [(base_year + t, annual_value) for t in range(1, horizon + 1)]


# ---------------------------------------------------------------------------
# GoalConfig validation
# ---------------------------------------------------------------------------


class TestGoalConfigValidation:
    def test_defaults(self) -> None:
        g = GoalConfig(target_annual_eur=Decimal("50000"))
        assert g.swr_rate == Decimal("0.0325")
        assert g.entities == ()
        assert g.require_all_vested is True

    def test_coerces_from_string(self) -> None:
        g = GoalConfig(target_annual_eur="50000", swr_rate="0.04")
        assert g.target_annual_eur == Decimal("50000")
        assert g.swr_rate == Decimal("0.04")

    def test_frozen(self) -> None:
        g = GoalConfig(target_annual_eur=Decimal("50000"))
        with pytest.raises(Exception):
            g.target_annual_eur = Decimal("60000")  # type: ignore[misc]

    def test_negative_target_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            GoalConfig(target_annual_eur=Decimal("-1"))

    def test_zero_target_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            GoalConfig(target_annual_eur=Decimal("0"))

    def test_swr_zero_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            GoalConfig(target_annual_eur=Decimal("50000"), swr_rate=Decimal("0"))

    def test_swr_above_one_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            GoalConfig(target_annual_eur=Decimal("50000"), swr_rate=Decimal("1.01"))

    def test_swr_exactly_one_allowed(self) -> None:
        g = GoalConfig(target_annual_eur=Decimal("50000"), swr_rate=Decimal("1"))
        assert g.swr_rate == Decimal("1")


# ---------------------------------------------------------------------------
# Basic evaluate behaviour
# ---------------------------------------------------------------------------


class TestEvaluateBasic:
    def test_empty_portfolio_raises(self) -> None:
        cfg = _simple_config()
        proj = project(cfg)
        goal = GoalConfig(target_annual_eur=Decimal("50000"))
        with pytest.raises(ValueError, match="empty"):
            evaluate(goal, proj, [])

    def test_goal_met_immediately(self) -> None:
        """SWR income alone exceeds target from year 1."""
        cfg = _simple_config(horizon=5)
        proj = project(cfg)
        # 3.25 % * 2_000_000 = 65_000 EUR > target 50_000
        portfolio = _portfolio_by_year(cfg.base_year, cfg.horizon_years, Decimal("2000000"))
        goal = GoalConfig(target_annual_eur=Decimal("50000"))
        result = evaluate(goal, proj, portfolio)
        assert result.goal_met is True
        assert result.year == cfg.base_year + 1
        assert result.surplus_eur > Decimal("0")

    def test_goal_never_met(self) -> None:
        """Portfolio is tiny; goal is never met within horizon."""
        cfg = _simple_config(horizon=5)
        proj = project(cfg)
        portfolio = _portfolio_by_year(cfg.base_year, cfg.horizon_years, Decimal("100"))
        goal = GoalConfig(target_annual_eur=Decimal("50000"))
        result = evaluate(goal, proj, portfolio)
        assert result.goal_met is False
        assert result.year is None
        assert result.surplus_eur < Decimal("0")

    def test_result_is_frozen(self) -> None:
        cfg = _simple_config()
        proj = project(cfg)
        goal = GoalConfig(target_annual_eur=Decimal("50000"))
        portfolio = _portfolio_by_year(cfg.base_year, cfg.horizon_years, Decimal("1000000"))
        result = evaluate(goal, proj, portfolio)
        with pytest.raises(Exception):
            result.goal_met = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SWR calculation
# ---------------------------------------------------------------------------


class TestSWRIncome:
    def test_swr_math(self) -> None:
        """SWR income = swr_rate * portfolio_value, rounded to 2 d.p."""
        cfg = _simple_config(horizon=1)
        proj = project(cfg)
        goal = GoalConfig(
            target_annual_eur=Decimal("0.01"),  # effectively zero target
            swr_rate=Decimal("0.04"),
        )
        portfolio = [(cfg.base_year + 1, Decimal("1000000"))]
        result = evaluate(goal, proj, portfolio)
        assert result.goal_met is True
        # 4 % * 1_000_000 = 40_000 EUR
        assert result.total_income_eur == Decimal("40000.00")

    def test_custom_swr_rate(self) -> None:
        cfg = _simple_config(horizon=1)
        proj = project(cfg)
        goal = GoalConfig(
            target_annual_eur=Decimal("20000"),
            swr_rate=Decimal("0.02"),
        )
        portfolio = [(cfg.base_year + 1, Decimal("1000000"))]
        result = evaluate(goal, proj, portfolio)
        # 2 % * 1_000_000 = 20_000 >= target 20_000
        assert result.goal_met is True
        assert result.surplus_eur == Decimal("0.00")


# ---------------------------------------------------------------------------
# Pension vesting
# ---------------------------------------------------------------------------


class TestPensionVesting:
    def test_vested_pension_counted(self) -> None:
        """Pension rules fully vested by year 1 are counted."""
        cfg = _simple_config(annual_pension_eur=Decimal("5000"), vesting_year=2025)
        proj = project(cfg)
        # Year 2025 = base_year + 1 → vesting satisfied → 1 * 5_000 cumulative
        # SWR contribution only: 0 (portfolio = 0)
        portfolio = [(2025, Decimal("0"))]
        goal = GoalConfig(target_annual_eur=Decimal("5000"))
        result = evaluate(goal, proj, portfolio)
        assert result.goal_met is True
        assert result.total_income_eur == Decimal("5000.00")

    def test_unvested_pension_excluded_require_all_vested(self) -> None:
        """With require_all_vested=True, pension not yet vested is excluded."""
        cfg = _simple_config(annual_pension_eur=Decimal("5000"), vesting_year=2035)
        proj = project(cfg)
        # Check year 2025: vesting_year 2035 > 2025, so pension excluded
        portfolio = [(2025, Decimal("0"))]
        goal = GoalConfig(
            target_annual_eur=Decimal("1"),  # tiny target
            require_all_vested=True,
        )
        result = evaluate(goal, proj, portfolio)
        # No SWR (portfolio = 0), no pension (not vested) → income = 0 < 1
        assert result.goal_met is False

    def test_unvested_pension_included_without_require(self) -> None:
        """With require_all_vested=False, unvested pension still counts."""
        cfg = _simple_config(annual_pension_eur=Decimal("5000"), vesting_year=2035)
        proj = project(cfg)
        portfolio = [(2025, Decimal("0"))]
        goal = GoalConfig(
            target_annual_eur=Decimal("4999"),
            require_all_vested=False,
        )
        result = evaluate(goal, proj, portfolio)
        # cumulative after 1 year = 5_000 (index=False) >= 4_999
        assert result.goal_met is True

    def test_vesting_year_boundary(self) -> None:
        """Vesting counts starting exactly on vesting_year."""
        cfg = _simple_config(annual_pension_eur=Decimal("5000"), vesting_year=2026)
        proj = project(cfg)
        # Year 2025: not yet vested; year 2026: vested
        goal = GoalConfig(target_annual_eur=Decimal("1"), require_all_vested=True)
        # Year 2025 check
        result_2025 = evaluate(goal, proj, [(2025, Decimal("0"))])
        assert result_2025.goal_met is False
        # Year 2026 check (cumulative = 2 * 5_000 = 10_000 after 2 years)
        result_2026 = evaluate(goal, proj, [(2026, Decimal("0"))])
        assert result_2026.goal_met is True


# ---------------------------------------------------------------------------
# Entity filtering
# ---------------------------------------------------------------------------


class TestEntityFiltering:
    def _two_entity_config(self) -> CashflowConfig:
        return CashflowConfig(
            base_year=2024,
            horizon_years=5,
            inflation_rate=Decimal("0.02"),
            eur_per_dkk=Decimal("0.134"),
            salaries=(
                SalaryRule(
                    entity="alice",
                    gross_annual=Decimal("80000"),
                    currency="EUR",
                    real_wage_growth=Decimal("0"),
                ),
                SalaryRule(
                    entity="bob",
                    gross_annual=Decimal("60000"),
                    currency="EUR",
                    real_wage_growth=Decimal("0"),
                ),
            ),
            contributions=(),
            pension_rules=(
                PensionAccrualRule(
                    entity="alice",
                    kind="annual_eur",
                    annual_eur=Decimal("3000"),
                    index_accrual_to_inflation=False,
                    vesting_year=2020,
                ),
                PensionAccrualRule(
                    entity="bob",
                    kind="annual_eur",
                    annual_eur=Decimal("2000"),
                    index_accrual_to_inflation=False,
                    vesting_year=2020,
                ),
            ),
        )

    def test_all_entities_included_by_default(self) -> None:
        cfg = self._two_entity_config()
        proj = project(cfg)
        goal = GoalConfig(target_annual_eur=Decimal("1"), entities=())
        result = evaluate(goal, proj, [(2025, Decimal("0"))])
        # alice: 3_000 + bob: 2_000 = 5_000
        assert result.total_income_eur == Decimal("5000.00")

    def test_single_entity_filter(self) -> None:
        cfg = self._two_entity_config()
        proj = project(cfg)
        goal = GoalConfig(target_annual_eur=Decimal("1"), entities=("alice",))
        result = evaluate(goal, proj, [(2025, Decimal("0"))])
        # alice only: 3_000
        assert result.total_income_eur == Decimal("3000.00")


# ---------------------------------------------------------------------------
# GoalResult fields
# ---------------------------------------------------------------------------


class TestGoalResult:
    def test_surplus_eur_when_met(self) -> None:
        cfg = _simple_config(horizon=1)
        proj = project(cfg)
        goal = GoalConfig(
            target_annual_eur=Decimal("30000"),
            swr_rate=Decimal("0.04"),
        )
        portfolio = [(2025, Decimal("1000000"))]
        result = evaluate(goal, proj, portfolio)
        # income = 40_000, target = 30_000 → surplus = 10_000
        assert result.surplus_eur == Decimal("10000.00")

    def test_shortfall_when_not_met(self) -> None:
        cfg = _simple_config(horizon=1)
        proj = project(cfg)
        goal = GoalConfig(
            target_annual_eur=Decimal("50000"),
            swr_rate=Decimal("0.04"),
        )
        portfolio = [(2025, Decimal("1000000"))]
        result = evaluate(goal, proj, portfolio)
        # income = 40_000, target = 50_000 → surplus = -10_000
        assert result.goal_met is False
        assert result.surplus_eur == Decimal("-10000.00")

    def test_goal_met_returns_first_year(self) -> None:
        """evaluate stops at the first year the goal is met."""
        cfg = _simple_config(horizon=5)
        proj = project(cfg)
        # Only year 2027 has enough portfolio
        portfolio = [
            (2025, Decimal("0")),
            (2026, Decimal("0")),
            (2027, Decimal("2000000")),
            (2028, Decimal("0")),
            (2029, Decimal("0")),
        ]
        goal = GoalConfig(target_annual_eur=Decimal("50000"))
        result = evaluate(goal, proj, portfolio)
        assert result.goal_met is True
        assert result.year == 2027
