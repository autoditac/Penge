"""Tests for penge.sim.routing — ASK cap overflow contribution router.

Scenario parameters (from issue #137):
    ASK opening balance:          62 000 DKK
    ASK cap:                     140 800 DKK
    Monthly contribution:         15 000 DKK
    Remaining ASK room:           78 800 DKK   (= 140 800 - 62 000)
    Annual contribution:         180 000 DKK   (= 15 000 x 12)

Year 1 split:
    ASK:        78 800 DKK  (= remaining room, cap exhausted mid-year)
    Frie midler: 101 200 DKK (= 180 000 - 78 800)

Year 2+ split:
    ASK:             0 DKK  (cap already fully absorbed)
    Frie midler: 180 000 DKK

Monthly detail (months 1-12):
    Months 1-5:  full 15 000 DKK to ASK
                 cumulative after month 5: 62 000 + 75 000 = 137 000 (room: 3 800)
    Month 6:     3 800 DKK to ASK (cap reached), 11 200 DKK to frie midler
                 cumulative after month 6: 140 800 (cap hit, room: 0)
    Months 7-12: 0 DKK to ASK, 15 000 DKK to frie midler
"""

from __future__ import annotations

from decimal import Decimal

import pydantic
import pytest

from penge.sim.liquid import LiquidDepotConfig, project_liquid, threshold_for_year
from penge.sim.routing import (
    ContributionRouter,
    ContributionRoutingError,
    MonthlyContributionSplit,
    YearlyContributionSplit,
    route_contributions,
    simulate_routing,
    simulate_routing_monthly,
)

# ─────────────────────────────────────────────────────────────────────────────
# Test fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────────

_ASK_CAP = Decimal("140800")
_INITIAL_DEPOSITS = Decimal("62000")
_MONTHLY = Decimal("15000")
_ANNUAL = Decimal("180000")  # 15 000 x 12
_REMAINING_ROOM = Decimal("78800")  # 140 800 - 62 000


def _router(
    *,
    ask_cap: str = "140800",
    cumulative: str = "62000",
    monthly: str = "15000",
) -> ContributionRouter:
    return ContributionRouter(
        ask_cap_dkk=Decimal(ask_cap),
        ask_cumulative_deposits_dkk=Decimal(cumulative),
        monthly_contribution_dkk=Decimal(monthly),
    )


# ─────────────────────────────────────────────────────────────────────────────
# ContributionRouter model validation
# ─────────────────────────────────────────────────────────────────────────────


class TestContributionRouterValidation:
    def test_valid_construction(self) -> None:
        r = _router()
        assert r.ask_cap_dkk == _ASK_CAP
        assert r.ask_cumulative_deposits_dkk == _INITIAL_DEPOSITS
        assert r.monthly_contribution_dkk == _MONTHLY

    def test_zero_monthly_contribution_allowed(self) -> None:
        r = _router(monthly="0")
        assert r.monthly_contribution_dkk == Decimal("0")

    def test_cap_exactly_exhausted_at_start(self) -> None:
        """Cumulative deposits == cap: all contributions go to frie midler."""
        r = _router(ask_cap="100000", cumulative="100000")
        ask, frie = route_contributions(r, 1)
        assert ask == Decimal("0")
        assert frie == _q("180000")

    def test_frozen_model(self) -> None:
        r = _router()
        with pytest.raises((pydantic.ValidationError, TypeError)):
            r.monthly_contribution_dkk = Decimal("1")  # frozen model raises ValidationError

    def test_negative_monthly_raises(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="must be ≥ 0"):
            ContributionRouter(
                ask_cap_dkk=Decimal("100000"),
                ask_cumulative_deposits_dkk=Decimal("0"),
                monthly_contribution_dkk=Decimal("-1"),
            )

    def test_negative_cumulative_raises(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="must be ≥ 0"):
            ContributionRouter(
                ask_cap_dkk=Decimal("100000"),
                ask_cumulative_deposits_dkk=Decimal("-1"),
                monthly_contribution_dkk=Decimal("1000"),
            )

    def test_zero_cap_raises(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="must be > 0"):
            ContributionRouter(
                ask_cap_dkk=Decimal("0"),
                ask_cumulative_deposits_dkk=Decimal("0"),
                monthly_contribution_dkk=Decimal("1000"),
            )

    def test_cumulative_exceeds_cap_raises(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="must be ≤ ask_cap_dkk"):
            ContributionRouter(
                ask_cap_dkk=Decimal("100000"),
                ask_cumulative_deposits_dkk=Decimal("100001"),
                monthly_contribution_dkk=Decimal("1000"),
            )

    def test_coercion_from_string(self) -> None:
        r = ContributionRouter(
            ask_cap_dkk="140800",  # type: ignore[arg-type]
            ask_cumulative_deposits_dkk="62000",  # type: ignore[arg-type]
            monthly_contribution_dkk="15000",  # type: ignore[arg-type]
        )
        assert r.ask_cap_dkk == Decimal("140800")

    def test_ask_cap_remaining_property(self) -> None:
        r = _router()
        assert r.ask_cap_remaining_dkk == _REMAINING_ROOM

    def test_annual_contribution_property(self) -> None:
        r = _router()
        assert r.annual_contribution_dkk == _ANNUAL


# ─────────────────────────────────────────────────────────────────────────────
# route_contributions — year-level split
# ─────────────────────────────────────────────────────────────────────────────


class TestRouteContributions:
    """Unit tests for the pure :func:`route_contributions` function."""

    def test_year_1_split(self) -> None:
        """Year 1: ASK receives remaining room; overflow goes to frie midler."""
        r = _router()
        ask, frie = route_contributions(r, 1)
        assert ask == _REMAINING_ROOM  # 78 800
        assert frie == _q("101200")  # 180 000 - 78 800
        assert ask + frie == _ANNUAL

    def test_year_2_all_frie_midler(self) -> None:
        """Year 2: cap already absorbed; 100 % to frie midler."""
        r = _router()
        ask, frie = route_contributions(r, 2)
        assert ask == Decimal("0")
        assert frie == _ANNUAL

    def test_year_3_to_10_all_frie_midler(self) -> None:
        r = _router()
        for yr in range(3, 11):
            ask, frie = route_contributions(r, yr)
            assert ask == Decimal("0"), f"year {yr}: expected 0 to ASK"
            assert frie == _ANNUAL, f"year {yr}: expected all to frie midler"

    def test_year_invalid_zero_raises(self) -> None:
        with pytest.raises(ContributionRoutingError, match="year must be ≥ 1"):
            route_contributions(_router(), 0)

    def test_year_invalid_negative_raises(self) -> None:
        with pytest.raises(ContributionRoutingError, match="year must be ≥ 1"):
            route_contributions(_router(), -5)

    def test_split_sums_to_annual(self) -> None:
        r = _router()
        for yr in range(1, 5):
            ask, frie = route_contributions(r, yr)
            assert ask + frie == _ANNUAL, f"year {yr}: split must sum to annual contribution"

    def test_no_room_from_start(self) -> None:
        """When cumulative already equals cap, all years go to frie midler."""
        r = _router(ask_cap="100000", cumulative="100000")
        for yr in range(1, 4):
            ask, frie = route_contributions(r, yr)
            assert ask == Decimal("0")
            assert frie == _q("180000")

    def test_room_exactly_one_annual_contribution(self) -> None:
        """Room == annual contribution: year 1 all to ASK, year 2 all to frie."""
        r = ContributionRouter(
            ask_cap_dkk=Decimal("280000"),
            ask_cumulative_deposits_dkk=Decimal("100000"),
            monthly_contribution_dkk=Decimal("15000"),
        )
        # Room = 280 000 - 100 000 = 180 000 == annual contribution
        ask1, frie1 = route_contributions(r, 1)
        assert ask1 == _ANNUAL
        assert frie1 == Decimal("0")

        ask2, frie2 = route_contributions(r, 2)
        assert ask2 == Decimal("0")
        assert frie2 == _ANNUAL


# ─────────────────────────────────────────────────────────────────────────────
# simulate_routing — multi-year projection
# ─────────────────────────────────────────────────────────────────────────────


class TestSimulateRouting:
    def test_returns_correct_number_of_years(self) -> None:
        splits = simulate_routing(_router(), n_years=10)
        assert len(splits) == 10

    def test_year_numbers_are_sequential(self) -> None:
        splits = simulate_routing(_router(), n_years=5)
        for i, s in enumerate(splits, start=1):
            assert s.year_number == i

    def test_year_1_values(self) -> None:
        splits = simulate_routing(_router(), n_years=3)
        s1 = splits[0]
        assert s1.year_number == 1
        assert s1.ask_contribution_dkk == _REMAINING_ROOM
        assert s1.frie_midler_contribution_dkk == _q("101200")
        assert s1.ask_cap_remaining_dkk == Decimal("0")
        assert s1.ask_cap_exhausted is True

    def test_year_2_values(self) -> None:
        splits = simulate_routing(_router(), n_years=3)
        s2 = splits[1]
        assert s2.year_number == 2
        assert s2.ask_contribution_dkk == Decimal("0")
        assert s2.frie_midler_contribution_dkk == _ANNUAL
        assert s2.ask_cap_remaining_dkk == Decimal("0")
        assert s2.ask_cap_exhausted is True

    def test_years_2_to_10_all_frie_midler(self) -> None:
        splits = simulate_routing(_router(), n_years=10)
        for s in splits[1:]:
            assert s.ask_contribution_dkk == Decimal("0"), f"year {s.year_number}"
            assert s.frie_midler_contribution_dkk == _ANNUAL, f"year {s.year_number}"
            assert s.ask_cap_exhausted is True, f"year {s.year_number}"

    def test_split_sums_to_annual_each_year(self) -> None:
        splits = simulate_routing(_router(), n_years=10)
        for s in splits:
            total = s.ask_contribution_dkk + s.frie_midler_contribution_dkk
            assert total == _ANNUAL, f"year {s.year_number}: sum {total} ≠ {_ANNUAL}"

    def test_n_years_invalid_raises(self) -> None:
        with pytest.raises(ContributionRoutingError, match="n_years must be ≥ 1"):
            simulate_routing(_router(), n_years=0)

    def test_cap_not_exhausted_flag_before_overflow_year(self) -> None:
        """When room > annual contribution, cap_exhausted stays False until it is hit."""
        r = ContributionRouter(
            ask_cap_dkk=Decimal("280000"),
            ask_cumulative_deposits_dkk=Decimal("0"),
            monthly_contribution_dkk=Decimal("10000"),
        )
        # Annual = 120 000; cap = 280 000; fills in years 1+2 (120k each) with 40k left year 3.
        splits = simulate_routing(r, n_years=4)
        assert splits[0].ask_cap_exhausted is False  # year 1: 120k deposited, 160k room left
        assert splits[1].ask_cap_exhausted is False  # year 2: 240k deposited, 40k room left
        assert splits[2].ask_cap_exhausted is True  # year 3: 280k cap reached
        assert splits[3].ask_cap_exhausted is True  # year 4: already exhausted

    def test_partial_fill_in_final_ask_year(self) -> None:
        """Year that partially fills ASK gets correct split and sets exhausted."""
        r = ContributionRouter(
            ask_cap_dkk=Decimal("280000"),
            ask_cumulative_deposits_dkk=Decimal("0"),
            monthly_contribution_dkk=Decimal("10000"),
        )
        splits = simulate_routing(r, n_years=4)
        # Year 3: only 40 000 room left out of 120 000 annual → partial fill
        s3 = splits[2]
        assert s3.ask_contribution_dkk == Decimal("40000")
        assert s3.frie_midler_contribution_dkk == _q("80000")
        assert s3.ask_cap_remaining_dkk == Decimal("0")
        assert s3.ask_cap_exhausted is True

    def test_consistency_with_route_contributions(self) -> None:
        """simulate_routing and route_contributions must agree for every year."""
        r = _router()
        splits = simulate_routing(r, n_years=5)
        for s in splits:
            ask, frie = route_contributions(r, s.year_number)
            assert s.ask_contribution_dkk == ask, f"year {s.year_number} ask mismatch"
            assert s.frie_midler_contribution_dkk == frie, f"year {s.year_number} frie mismatch"


# ─────────────────────────────────────────────────────────────────────────────
# simulate_routing_monthly — monthly detail
# ─────────────────────────────────────────────────────────────────────────────


class TestSimulateRoutingMonthly:
    """Monthly granularity: cap exhausted in month 6 (after 5 full months to ASK)."""

    def test_months_1_to_5_all_to_ask(self) -> None:
        """Months 1-5: full 15 000 DKK each month goes to ASK."""
        months = simulate_routing_monthly(_router(), n_months=12)
        for m in months[:5]:
            assert m.ask_contribution_dkk == _MONTHLY, f"month {m.month_number}"
            assert m.frie_midler_contribution_dkk == Decimal("0"), f"month {m.month_number}"

    def test_cumulative_after_5_months(self) -> None:
        """After 5 months: 62 000 + 5 x 15 000 = 137 000 DKK deposited."""
        months = simulate_routing_monthly(_router(), n_months=6)
        assert months[4].cumulative_ask_deposits_dkk == Decimal("137000")

    def test_month_6_cap_hit(self) -> None:
        """Month 6: only 3 800 DKK room remains; 11 200 DKK overflows to frie midler."""
        months = simulate_routing_monthly(_router(), n_months=12)
        m6 = months[5]  # 0-indexed: month_number == 6
        assert m6.month_number == 6
        assert m6.ask_contribution_dkk == Decimal("3800")
        assert m6.frie_midler_contribution_dkk == Decimal("11200")
        assert m6.cumulative_ask_deposits_dkk == Decimal("140800")

    def test_months_7_to_12_all_to_frie(self) -> None:
        """Months 7-12: cap exhausted; 15 000 DKK each month to frie midler."""
        months = simulate_routing_monthly(_router(), n_months=12)
        for m in months[6:]:
            assert m.ask_contribution_dkk == Decimal("0"), f"month {m.month_number}"
            assert m.frie_midler_contribution_dkk == _MONTHLY, f"month {m.month_number}"
            assert m.cumulative_ask_deposits_dkk == Decimal("140800")

    def test_split_sums_to_monthly_each_month(self) -> None:
        months = simulate_routing_monthly(_router(), n_months=24)
        for m in months:
            total = m.ask_contribution_dkk + m.frie_midler_contribution_dkk
            assert total == _MONTHLY, f"month {m.month_number}: sum {total} ≠ {_MONTHLY}"

    def test_cumulative_is_monotone_nondecreasing(self) -> None:
        months = simulate_routing_monthly(_router(), n_months=24)
        for i in range(1, len(months)):
            prev = months[i - 1].cumulative_ask_deposits_dkk
            assert months[i].cumulative_ask_deposits_dkk >= prev

    def test_cumulative_never_exceeds_cap(self) -> None:
        months = simulate_routing_monthly(_router(), n_months=36)
        for m in months:
            assert m.cumulative_ask_deposits_dkk <= _ASK_CAP

    def test_yearly_ask_total_matches_simulate_routing(self) -> None:
        """Sum of monthly ASK contributions over 12 months = yearly split year 1."""
        months = simulate_routing_monthly(_router(), n_months=12)
        monthly_ask_total = sum(m.ask_contribution_dkk for m in months)
        splits = simulate_routing(_router(), n_years=1)
        assert monthly_ask_total == splits[0].ask_contribution_dkk

    def test_n_months_invalid_raises(self) -> None:
        with pytest.raises(ContributionRoutingError, match="n_months must be ≥ 1"):
            simulate_routing_monthly(_router(), n_months=0)

    def test_month_numbers_are_sequential(self) -> None:
        months = simulate_routing_monthly(_router(), n_months=6)
        for i, m in enumerate(months, start=1):
            assert m.month_number == i


# ─────────────────────────────────────────────────────────────────────────────
# Edge cases and boundary conditions
# ─────────────────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_zero_monthly_contribution(self) -> None:
        r = _router(monthly="0")
        splits = simulate_routing(r, n_years=5)
        for s in splits:
            assert s.ask_contribution_dkk == Decimal("0")
            assert s.frie_midler_contribution_dkk == Decimal("0")
            # No deposits → cap never exhausted (remaining room unchanged)
            assert s.ask_cap_remaining_dkk == Decimal("78800")
            assert s.ask_cap_exhausted is False

    def test_very_large_monthly_contribution(self) -> None:
        """Single month fills the entire ASK room; no overflow needed."""
        r = ContributionRouter(
            ask_cap_dkk=Decimal("140800"),
            ask_cumulative_deposits_dkk=Decimal("62000"),
            monthly_contribution_dkk=Decimal("100000"),
        )
        # Annual = 1 200 000; room = 78 800
        ask, frie = route_contributions(r, 1)
        assert ask == Decimal("78800")
        assert frie == Decimal("1200000") - Decimal("78800")

    def test_fractional_monthly_contribution(self) -> None:
        """Decimal contributions are handled without precision loss."""
        r = ContributionRouter(
            ask_cap_dkk=Decimal("10000"),
            ask_cumulative_deposits_dkk=Decimal("0"),
            monthly_contribution_dkk=Decimal("833.33"),
        )
        months = simulate_routing_monthly(r, n_months=12)
        # Annual = 833.33 x 12 = 9 999.96 < 10 000 → year 1 all to ASK
        total_ask = sum(m.ask_contribution_dkk for m in months)
        total_frie = sum(m.frie_midler_contribution_dkk for m in months)
        assert total_ask + total_frie == Decimal("833.33") * 12

    def test_fractional_contribution_route_consistency(self) -> None:
        """route_contributions and simulate_routing agree for fractional inputs."""
        r = ContributionRouter(
            ask_cap_dkk=Decimal("10000"),
            ask_cumulative_deposits_dkk=Decimal("7000"),
            monthly_contribution_dkk=Decimal("333.33"),
        )
        # Annual = 333.33 x 12 = 3 999.96; remaining room = 3 000
        # Year 1: ASK = 3 000, frie = 999.96
        # Year 2: ASK = 0,     frie = 3 999.96
        splits = simulate_routing(r, n_years=5)
        for k, split in enumerate(splits, start=1):
            rc_ask, rc_frie = route_contributions(r, k)
            assert rc_ask == split.ask_contribution_dkk, f"year {k}: ask mismatch"
            assert rc_frie == split.frie_midler_contribution_dkk, f"year {k}: frie mismatch"

    def test_single_year_simulation(self) -> None:
        splits = simulate_routing(_router(), n_years=1)
        assert len(splits) == 1
        assert splits[0].year_number == 1

    def test_route_contributions_agrees_for_large_year(self) -> None:
        """route_contributions for a far-future year always gives all frie midler."""
        r = _router()
        ask, frie = route_contributions(r, 100)
        assert ask == Decimal("0")
        assert frie == _ANNUAL

    def test_cap_exactly_one_month_away(self) -> None:
        """Room == monthly contribution: month 1 fills ASK exactly, month 2 all frie."""
        r = ContributionRouter(
            ask_cap_dkk=Decimal("77000"),
            ask_cumulative_deposits_dkk=Decimal("62000"),
            monthly_contribution_dkk=Decimal("15000"),
        )
        # Room = 15 000 exactly
        months = simulate_routing_monthly(r, n_months=3)
        assert months[0].ask_contribution_dkk == Decimal("15000")
        assert months[0].frie_midler_contribution_dkk == Decimal("0")
        assert months[1].ask_contribution_dkk == Decimal("0")
        assert months[1].frie_midler_contribution_dkk == Decimal("15000")

    def test_output_types_are_frozen_pydantic_models(self) -> None:
        splits = simulate_routing(_router(), n_years=2)
        for s in splits:
            assert isinstance(s, YearlyContributionSplit)

        months = simulate_routing_monthly(_router(), n_months=2)
        for m in months:
            assert isinstance(m, MonthlyContributionSplit)

    def test_monthly_ask_cap_exhausted_flag(self) -> None:
        """ask_cap_exhausted is False before month 6 and True from month 6 onward."""
        months = simulate_routing_monthly(_router(), n_months=12)
        for m in months[:5]:
            assert m.ask_cap_exhausted is False, f"month {m.month_number} should not be exhausted"
        for m in months[5:]:
            assert m.ask_cap_exhausted is True, f"month {m.month_number} should be exhausted"

    def test_monthly_ask_cap_remaining_drops_to_zero(self) -> None:
        """ask_cap_remaining_dkk reaches zero at month 6 and stays zero."""
        months = simulate_routing_monthly(_router(), n_months=12)
        assert months[4].ask_cap_remaining_dkk == Decimal("3800")
        assert months[5].ask_cap_remaining_dkk == Decimal("0")
        for m in months[5:]:
            assert m.ask_cap_remaining_dkk == Decimal("0"), f"month {m.month_number}"


# ─────────────────────────────────────────────────────────────────────────────
# Integration smoke test: routing → LiquidDepotConfig → project_liquid
# ─────────────────────────────────────────────────────────────────────────────


class TestLiquidIntegration:
    """Smoke-test the wiring from simulate_routing into project_liquid.

    Verifies the contract stated in the routing module docstring: yearly
    contribution splits from simulate_routing feed into two separate
    LiquidDepotConfig instances (one ASK, one frie midler) which are then
    projected with project_liquid.
    """

    def test_two_depot_projection_from_routing_output(self) -> None:
        router = ContributionRouter(
            ask_cap_dkk=Decimal("140800"),
            ask_cumulative_deposits_dkk=Decimal("62000"),
            monthly_contribution_dkk=Decimal("15000"),
        )
        splits = simulate_routing(router, n_years=3)
        # Year 1: ASK = 78 800, frie = 101 200
        # Years 2-3: ASK = 0, frie = 180 000

        base_year = 2025
        threshold = threshold_for_year(base_year + 1)

        ask_config = LiquidDepotConfig(
            account_id="ask",
            account_type="ask",
            tax_regime="lager",
            opening_balance_dkk=Decimal("62000"),
            ask_lifetime_deposits_dkk=Decimal("62000"),
            annual_contribution_dkk=splits[0].ask_contribution_dkk,
            gross_annual_return_rate=Decimal("0.07"),
            annual_expense_ratio=Decimal("0.002"),
            aktieindkomst_threshold_dkk=threshold,
        )
        frie_config = LiquidDepotConfig(
            account_id="frie-midler",
            account_type="frie_midler",
            tax_regime="lager",
            opening_balance_dkk=Decimal("0"),
            annual_contribution_dkk=splits[0].frie_midler_contribution_dkk,
            gross_annual_return_rate=Decimal("0.07"),
            annual_expense_ratio=Decimal("0.002"),
            aktieindkomst_threshold_dkk=threshold,
        )

        ask_projection = project_liquid(ask_config, base_year=base_year, horizon_years=3)
        frie_projection = project_liquid(frie_config, base_year=base_year, horizon_years=3)

        # Both projections succeed and have the right length
        assert len(ask_projection.flows) == 3
        assert len(frie_projection.flows) == 3

        # Year 1 ASK contribution matches routing split
        ask_year1 = ask_projection.flows[0]
        assert ask_year1.annual_contribution_dkk == splits[0].ask_contribution_dkk

        # Closing balances are positive (compounding occurred)
        assert ask_projection.flows[-1].closing_balance_dkk > Decimal("0")
        assert frie_projection.flows[-1].closing_balance_dkk > Decimal("0")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _q(v: str) -> Decimal:
    return Decimal(v)
