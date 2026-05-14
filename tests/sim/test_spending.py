"""Tests for penge.sim.spending — household spending and target-expense model.

All fixtures use synthetic data only.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

import pytest

from penge.sim.spending import (
    HouseholdSpendingPlan,
    OneOffExpense,
    SpendingPhase,
    SpendingRule,
    compute_spending,
)

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

_ACC = SpendingPhase.ACCUMULATION
_BRG = SpendingPhase.BRIDGE
_RET = SpendingPhase.RETIREMENT


def _rule(
    label: str = "living",
    annual_amount: str = "30000",
    currency: Literal["EUR", "DKK"] = "EUR",
    phase: SpendingPhase | None = None,
    active_from: int | None = None,
    active_until: int | None = None,
    inflation_rate: str = "0.02",
    inflation_base_year: int | None = None,
) -> SpendingRule:
    return SpendingRule(
        label=label,
        annual_amount=Decimal(annual_amount),
        currency=currency,
        phase=phase,
        active_from=active_from,
        active_until=active_until,
        inflation_rate=Decimal(inflation_rate),
        inflation_base_year=inflation_base_year,
    )


def _one_off(
    label: str = "car",
    year: int = 2030,
    amount: str = "10000",
    currency: Literal["EUR", "DKK"] = "EUR",
) -> OneOffExpense:
    return OneOffExpense(
        label=label,
        year=year,
        amount=Decimal(amount),
        currency=currency,
    )


# ---------------------------------------------------------------------------
# 1. Single rule, all phases, no bounds
# ---------------------------------------------------------------------------


def test_single_rule_no_bounds_all_phases() -> None:
    """A rule with no phase and no bounds applies to every year and phase."""
    rule = _rule(annual_amount="30000", currency="EUR")
    plan = HouseholdSpendingPlan(rules=[rule])

    for phase in (_ACC, _BRG, _RET):
        result = compute_spending(plan, 2030, phase)
        assert result["EUR"] == Decimal("30000")
        assert result["DKK"] == Decimal("0")


# ---------------------------------------------------------------------------
# 2. Rule with active_from only
# ---------------------------------------------------------------------------


def test_active_from_before_activation_year() -> None:
    """A rule with active_from=2030 is inactive in 2029."""
    rule = _rule(active_from=2030)
    plan = HouseholdSpendingPlan(rules=[rule])

    result = compute_spending(plan, 2029, _ACC)
    assert result["EUR"] == Decimal("0")


def test_active_from_at_activation_year() -> None:
    """A rule with active_from=2030 is active in 2030."""
    rule = _rule(active_from=2030, inflation_rate="0")
    plan = HouseholdSpendingPlan(rules=[rule])

    result = compute_spending(plan, 2030, _ACC)
    assert result["EUR"] == Decimal("30000")


def test_active_from_after_activation_year() -> None:
    """A rule with active_from=2030 is active in 2031."""
    rule = _rule(active_from=2030, inflation_rate="0")
    plan = HouseholdSpendingPlan(rules=[rule])

    result = compute_spending(plan, 2031, _ACC)
    assert result["EUR"] == Decimal("30000")


# ---------------------------------------------------------------------------
# 3. Rule with active_until only
# ---------------------------------------------------------------------------


def test_active_until_before_cutoff() -> None:
    """A rule with active_until=2040 is active in 2040."""
    rule = _rule(active_until=2040, inflation_rate="0")
    plan = HouseholdSpendingPlan(rules=[rule])

    result = compute_spending(plan, 2040, _ACC)
    assert result["EUR"] == Decimal("30000")


def test_active_until_after_cutoff() -> None:
    """A rule with active_until=2040 is inactive in 2041."""
    rule = _rule(active_until=2040)
    plan = HouseholdSpendingPlan(rules=[rule])

    result = compute_spending(plan, 2041, _ACC)
    assert result["EUR"] == Decimal("0")


# ---------------------------------------------------------------------------
# 4. Rule with both bounds
# ---------------------------------------------------------------------------


def test_both_bounds_inside() -> None:
    """Rule active_from=2030, active_until=2035 is active in 2032."""
    rule = _rule(active_from=2030, active_until=2035, inflation_rate="0")
    plan = HouseholdSpendingPlan(rules=[rule])

    assert compute_spending(plan, 2032, _ACC)["EUR"] == Decimal("30000")


def test_both_bounds_on_lower_boundary() -> None:
    """Rule active_from=2030, active_until=2035 is active exactly at 2030."""
    rule = _rule(active_from=2030, active_until=2035, inflation_rate="0")
    plan = HouseholdSpendingPlan(rules=[rule])

    assert compute_spending(plan, 2030, _ACC)["EUR"] == Decimal("30000")


def test_both_bounds_on_upper_boundary() -> None:
    """Rule active_from=2030, active_until=2035 is active exactly at 2035."""
    rule = _rule(active_from=2030, active_until=2035, inflation_rate="0")
    plan = HouseholdSpendingPlan(rules=[rule])

    assert compute_spending(plan, 2035, _ACC)["EUR"] == Decimal("30000")


def test_both_bounds_before_range() -> None:
    """Rule active_from=2030, active_until=2035 is inactive in 2029."""
    rule = _rule(active_from=2030, active_until=2035)
    plan = HouseholdSpendingPlan(rules=[rule])

    assert compute_spending(plan, 2029, _ACC)["EUR"] == Decimal("0")


def test_both_bounds_after_range() -> None:
    """Rule active_from=2030, active_until=2035 is inactive in 2036."""
    rule = _rule(active_from=2030, active_until=2035)
    plan = HouseholdSpendingPlan(rules=[rule])

    assert compute_spending(plan, 2036, _ACC)["EUR"] == Decimal("0")


# ---------------------------------------------------------------------------
# 5. Phase filtering
# ---------------------------------------------------------------------------


def test_bridge_rule_absent_in_retirement() -> None:
    """A BRIDGE-phase rule does not appear when phase=RETIREMENT."""
    rule = _rule(phase=_BRG, annual_amount="20000")
    plan = HouseholdSpendingPlan(rules=[rule])

    result = compute_spending(plan, 2040, _RET)
    assert result["EUR"] == Decimal("0")


def test_bridge_rule_present_in_bridge() -> None:
    """A BRIDGE-phase rule is included when phase=BRIDGE."""
    rule = _rule(phase=_BRG, annual_amount="20000", inflation_rate="0")
    plan = HouseholdSpendingPlan(rules=[rule])

    result = compute_spending(plan, 2040, _BRG)
    assert result["EUR"] == Decimal("20000")


def test_accumulation_rule_absent_in_bridge() -> None:
    """An ACCUMULATION rule does not appear in BRIDGE."""
    rule = _rule(phase=_ACC, annual_amount="15000")
    plan = HouseholdSpendingPlan(rules=[rule])

    result = compute_spending(plan, 2035, _BRG)
    assert result["EUR"] == Decimal("0")


def test_none_phase_applies_to_all() -> None:
    """A rule with phase=None applies to ACCUMULATION, BRIDGE, and RETIREMENT."""
    rule = _rule(phase=None, annual_amount="12000", inflation_rate="0")
    plan = HouseholdSpendingPlan(rules=[rule])

    for phase in (_ACC, _BRG, _RET):
        assert compute_spending(plan, 2030, phase)["EUR"] == Decimal("12000")


# ---------------------------------------------------------------------------
# 6. Inflation indexing
# ---------------------------------------------------------------------------


def test_inflation_no_compounding_when_base_is_year() -> None:
    """When neither active_from nor inflation_base_year is set, no compounding occurs."""
    rule = _rule(annual_amount="10000", inflation_rate="0.05")
    plan = HouseholdSpendingPlan(rules=[rule])

    # base_year defaults to year itself → 0 periods → no growth
    result = compute_spending(plan, 2030, _ACC)
    assert result["EUR"] == Decimal("10000")


def test_inflation_compounding_with_active_from() -> None:
    """Verify exact compound growth when base_year derives from active_from.

    Base year = 2025, target = 2030, rate = 2 %:
    10 000 * 1.02 ** 5 = 11 040.81 (rounded to 2 d.p.)
    """
    expected = (Decimal("10000") * Decimal("1.02") ** 5).quantize(Decimal("0.01"))
    rule = _rule(annual_amount="10000", active_from=2025, inflation_rate="0.02")
    plan = HouseholdSpendingPlan(rules=[rule])

    result = compute_spending(plan, 2030, _ACC)
    assert result["EUR"] == expected


def test_inflation_compounding_with_explicit_base_year() -> None:
    """Explicit inflation_base_year overrides active_from.

    Base year = 2020, target = 2030, rate = 3 %:
    5 000 * 1.03 ** 10
    """
    expected = (Decimal("5000") * Decimal("1.03") ** 10).quantize(Decimal("0.01"))
    rule = _rule(
        annual_amount="5000",
        active_from=2025,
        inflation_rate="0.03",
        inflation_base_year=2020,
    )
    plan = HouseholdSpendingPlan(rules=[rule])

    result = compute_spending(plan, 2030, _ACC)
    assert result["EUR"] == expected


def test_inflation_zero_rate_no_growth() -> None:
    """Zero inflation rate means amount is constant regardless of year gap."""
    rule = _rule(annual_amount="20000", active_from=2020, inflation_rate="0")
    plan = HouseholdSpendingPlan(rules=[rule])

    result = compute_spending(plan, 2040, _ACC)
    assert result["EUR"] == Decimal("20000")


# ---------------------------------------------------------------------------
# 7. One-off expenses
# ---------------------------------------------------------------------------


def test_one_off_appears_in_correct_year() -> None:
    """A one-off expense is included in its target year."""
    one_off = _one_off(year=2032, amount="15000", currency="EUR")
    plan = HouseholdSpendingPlan(one_offs=[one_off])

    result = compute_spending(plan, 2032, _ACC)
    assert result["EUR"] == Decimal("15000")


def test_one_off_absent_in_other_years() -> None:
    """A one-off expense does not appear in any other year."""
    one_off = _one_off(year=2032, amount="15000", currency="EUR")
    plan = HouseholdSpendingPlan(one_offs=[one_off])

    assert compute_spending(plan, 2031, _ACC)["EUR"] == Decimal("0")
    assert compute_spending(plan, 2033, _ACC)["EUR"] == Decimal("0")


def test_one_off_dkk_currency() -> None:
    """A DKK one-off expense is summed in the DKK bucket, not EUR."""
    one_off = _one_off(year=2030, amount="50000", currency="DKK")
    plan = HouseholdSpendingPlan(one_offs=[one_off])

    result = compute_spending(plan, 2030, _ACC)
    assert result["EUR"] == Decimal("0")
    assert result["DKK"] == Decimal("50000")


# ---------------------------------------------------------------------------
# 8. EUR and DKK isolation
# ---------------------------------------------------------------------------


def test_eur_and_dkk_do_not_cross_contaminate() -> None:
    """EUR and DKK spending rules sum into separate buckets."""
    eur_rule = _rule(label="eur_living", annual_amount="24000", currency="EUR", inflation_rate="0")
    dkk_rule = _rule(label="dkk_living", annual_amount="180000", currency="DKK", inflation_rate="0")
    plan = HouseholdSpendingPlan(rules=[eur_rule, dkk_rule])

    result = compute_spending(plan, 2030, _ACC)
    assert result["EUR"] == Decimal("24000")
    assert result["DKK"] == Decimal("180000")


def test_multiple_eur_rules_summed() -> None:
    """Multiple EUR rules are summed into a single EUR total."""
    rules = [
        _rule(label="rent", annual_amount="18000", currency="EUR", inflation_rate="0"),
        _rule(label="food", annual_amount="6000", currency="EUR", inflation_rate="0"),
        _rule(label="transport", annual_amount="3000", currency="EUR", inflation_rate="0"),
    ]
    plan = HouseholdSpendingPlan(rules=rules)

    result = compute_spending(plan, 2030, _ACC)
    assert result["EUR"] == Decimal("27000")


# ---------------------------------------------------------------------------
# 9. Validation errors
# ---------------------------------------------------------------------------


def test_active_from_greater_than_active_until_raises() -> None:
    """active_from > active_until must raise ValueError."""
    with pytest.raises(ValueError, match="active_from"):
        SpendingRule(
            label="bad",
            annual_amount=Decimal("10000"),
            currency="EUR",
            active_from=2035,
            active_until=2030,
        )


def test_one_off_non_positive_amount_raises() -> None:
    """OneOffExpense with non-positive amount must raise ValueError."""
    with pytest.raises(ValueError, match="positive"):
        OneOffExpense(label="zero", year=2030, amount=Decimal("0"), currency="EUR")


def test_spending_rule_non_positive_amount_raises() -> None:
    """SpendingRule with non-positive annual_amount must raise ValueError."""
    with pytest.raises(ValueError, match="positive"):
        SpendingRule(label="zero", annual_amount=Decimal("-1"), currency="EUR")


# ---------------------------------------------------------------------------
# 10. FIRE integration: phase-specific spending
# ---------------------------------------------------------------------------


def test_fire_phase_specific_spending() -> None:
    """FIRE integration: accumulation has salary-era expenses; bridge is lower.

    During accumulation: rent (12 000) + food (6 000) + commute (2 400) = 20 400 EUR.
    During bridge:       rent (12 000) + food (6 000) = 18 000 EUR (commute gone).
    During retirement:   rent (10 000) + food (5 000) = 15 000 EUR (different rules).
    """
    rent_all = _rule(
        label="rent",
        annual_amount="12000",
        currency="EUR",
        phase=None,
        active_until=2044,
        inflation_rate="0",
    )
    food_accum_bridge = _rule(
        label="food_accum_bridge",
        annual_amount="6000",
        currency="EUR",
        phase=None,
        active_until=2049,
        inflation_rate="0",
    )
    commute = _rule(
        label="commute",
        annual_amount="2400",
        currency="EUR",
        phase=_ACC,
        inflation_rate="0",
    )
    rent_ret = _rule(
        label="rent_retirement",
        annual_amount="10000",
        currency="EUR",
        phase=_RET,
        active_from=2050,
        inflation_rate="0",
    )
    food_ret = _rule(
        label="food_retirement",
        annual_amount="5000",
        currency="EUR",
        phase=_RET,
        active_from=2050,
        inflation_rate="0",
    )

    plan = HouseholdSpendingPlan(rules=[rent_all, food_accum_bridge, commute, rent_ret, food_ret])

    # Accumulation in 2035: rent + food + commute
    acc_result = compute_spending(plan, 2035, _ACC)
    assert acc_result["EUR"] == Decimal("20400")

    # Bridge in 2040: rent + food (no commute)
    brg_result = compute_spending(plan, 2040, _BRG)
    assert brg_result["EUR"] == Decimal("18000")

    # Retirement in 2055: rent_retirement + food_retirement (prior rules expired/filtered)
    ret_result = compute_spending(plan, 2055, _RET)
    # rent_all expired 2044, food_accum_bridge expired 2049
    # commute is phase=ACCUMULATION → filtered
    # rent_ret + food_ret = 15 000
    assert ret_result["EUR"] == Decimal("15000")


def test_fire_bridge_lower_than_accumulation() -> None:
    """Bridge-phase spending total is strictly less than accumulation total."""
    work_costs = _rule(
        label="work_costs",
        annual_amount="5000",
        currency="EUR",
        phase=_ACC,
        inflation_rate="0",
    )
    base = _rule(
        label="base",
        annual_amount="20000",
        currency="EUR",
        phase=None,
        inflation_rate="0",
    )
    plan = HouseholdSpendingPlan(rules=[work_costs, base])

    acc = compute_spending(plan, 2030, _ACC)["EUR"]
    brg = compute_spending(plan, 2030, _BRG)["EUR"]
    assert brg < acc
    assert acc == Decimal("25000")
    assert brg == Decimal("20000")
