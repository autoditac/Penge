"""Tests for penge.sim.config_compare — side-by-side CashflowConfig comparison.

All fixtures are synthetic.  Closes #127.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from penge.sim.cashflow import (
    CashflowConfig,
    ContributionRule,
    PensionAccrualRule,
    SalaryRule,
)
from penge.sim.config_compare import (
    ConfigCompareError,
    ConfigComparison,
    ConfigComparisonResult,
    compare_configs,
)


def _config(
    *,
    horizon: int = 20,
    annual_contrib: str = "12000",
    accrual_fraction: str = "0.18",
) -> CashflowConfig:
    """Build a small synthetic config for one entity ('alice', EUR)."""
    contrib = ContributionRule(
        entity="alice",
        currency="EUR",
        annual=Decimal(annual_contrib),
        index_to_inflation=False,
    )
    salary = SalaryRule(
        entity="alice",
        currency="EUR",
        gross_annual=Decimal("60000"),
        real_wage_growth=Decimal("0"),
    )
    accrual = PensionAccrualRule(
        entity="alice",
        kind="dc_fraction",
        dc_fraction=Decimal(accrual_fraction),
        vesting_year=2060,
    )
    return CashflowConfig(
        base_year=2024,
        horizon_years=horizon,
        inflation_rate=Decimal("0"),
        eur_per_dkk=Decimal("0.134"),
        salaries=(salary,),
        contributions=(contrib,),
        pension_rules=(accrual,),
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_compare_configs_requires_at_least_one_scenario() -> None:
    with pytest.raises(ConfigCompareError, match="at least one"):
        compare_configs()


def test_compare_configs_rejects_empty_label() -> None:
    with pytest.raises(ConfigCompareError, match="non-empty"):
        compare_configs(("", _config()))


def test_compare_configs_rejects_duplicate_labels() -> None:
    cfg = _config()
    with pytest.raises(ConfigCompareError, match="duplicate"):
        compare_configs(("base", cfg), ("base", cfg))


# ---------------------------------------------------------------------------
# Single-scenario passthrough
# ---------------------------------------------------------------------------


def test_compare_configs_accepts_single_scenario() -> None:
    cfg = _config(horizon=5)
    cmp = compare_configs(("only", cfg))
    assert isinstance(cmp, ConfigComparison)
    assert cmp.labels() == ["only"]
    only = cmp.by_label("only")
    assert isinstance(only, ConfigComparisonResult)
    assert only.config is cfg
    assert "alice" in only.end_balance_eur
    assert only.end_balance_eur["alice"] > Decimal("0")


# ---------------------------------------------------------------------------
# Coast FIRE comparison: pay 20y vs. stop after 10y
# ---------------------------------------------------------------------------


def test_high_vs_low_contribution_comparison() -> None:
    """A higher contribution stream produces a higher liquid total.

    Note: a stricter "Coast FIRE" comparison (stop contributions partway
    through the horizon) requires the time-bounded rule fields tracked in
    issue #125.  Once those land, an additional test exercising
    ``active_until`` should be added here.
    """
    high = _config(horizon=20, annual_contrib="24000", accrual_fraction="0.21")
    low = _config(horizon=20, annual_contrib="12000", accrual_fraction="0.12")

    cmp = compare_configs(
        ("high_contrib", high),
        ("low_contrib", low),
    )

    assert cmp.labels() == ["high_contrib", "low_contrib"]
    h = cmp.by_label("high_contrib")
    lo = cmp.by_label("low_contrib")

    assert h.end_balance_eur["alice"] > lo.end_balance_eur["alice"]
    assert h.total_contributions_eur["alice"] > lo.total_contributions_eur["alice"]
    assert h.total_contributions_eur["alice"] == Decimal("24000") * 20
    assert lo.total_contributions_eur["alice"] == Decimal("12000") * 20

    diff = cmp.diff_end_balance_eur("high_contrib", "low_contrib")
    assert diff["alice"] < Decimal("0")


def test_total_liquid_currently_equals_total_contributions() -> None:
    """Until tax-aware liquid balance lands, the two summary metrics agree."""
    cmp = compare_configs(("a", _config(horizon=5)))
    only = cmp.by_label("a")
    assert only.total_liquid_eur == only.total_contributions_eur


def test_by_label_unknown_raises_keyerror() -> None:
    cmp = compare_configs(("a", _config(horizon=5)))
    with pytest.raises(KeyError):
        cmp.by_label("missing")


def test_diff_end_balance_handles_disjoint_entities() -> None:
    cfg_a = _config(horizon=5)

    contrib = ContributionRule(
        entity="bob",
        currency="EUR",
        annual=Decimal("9000"),
        index_to_inflation=False,
    )
    salary = SalaryRule(
        entity="bob",
        currency="EUR",
        gross_annual=Decimal("50000"),
        real_wage_growth=Decimal("0"),
    )
    accrual = PensionAccrualRule(
        entity="bob",
        kind="dc_fraction",
        dc_fraction=Decimal("0.18"),
        vesting_year=2060,
    )
    cfg_b = CashflowConfig(
        base_year=2024,
        horizon_years=5,
        inflation_rate=Decimal("0"),
        eur_per_dkk=Decimal("0.134"),
        salaries=(salary,),
        contributions=(contrib,),
        pension_rules=(accrual,),
    )

    cmp = compare_configs(("alice_only", cfg_a), ("bob_only", cfg_b))
    diff = cmp.diff_end_balance_eur("alice_only", "bob_only")

    assert "alice" in diff and "bob" in diff
    assert diff["alice"] < Decimal("0")
    assert diff["bob"] > Decimal("0")
