"""Tests for the pure returns engine (TWR, MWR/XIRR).

Golden cases are closed-form: constant growth, single flows, known
XIRR algebra. Property-based tests assert the structural invariants
from ADR-0039.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pydantic
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from penge.analytics import (
    MIN_ANNUALIZE_DAYS,
    ReturnPoint,
    ReturnsError,
    TwrSummary,
    chain_linked_twr,
    mwr_from_series,
    twr_summary,
    xirr,
)

_D0 = date(2024, 1, 1)


def _series(rows: list[tuple[str, str, str]]) -> list[ReturnPoint]:
    """Build contiguous daily points from (begin, end, flow) triples."""
    return [
        ReturnPoint(
            as_of=_D0 + timedelta(days=i),
            begin_value=Decimal(begin),
            end_value=Decimal(end),
            net_flow=Decimal(flow),
        )
        for i, (begin, end, flow) in enumerate(rows)
    ]


# --- ReturnPoint ------------------------------------------------------------


def test_factor_start_of_day_flow_convention() -> None:
    point = ReturnPoint(
        as_of=_D0,
        begin_value=Decimal("1000"),
        end_value=Decimal("1111"),
        net_flow=Decimal("100"),
    )
    assert point.denominator == Decimal("1100")
    assert point.factor == Decimal("1111") / Decimal("1100")


def test_factor_is_none_without_capital_at_risk() -> None:
    point = ReturnPoint(as_of=_D0, begin_value=Decimal("0"), end_value=Decimal("0"))
    assert point.factor is None


# --- chain_linked_twr -------------------------------------------------------


def test_chain_link_empty_is_identity() -> None:
    assert chain_linked_twr([]) == Decimal("1")


def test_chain_link_golden() -> None:
    factors = [Decimal("1.10"), Decimal("0.90"), Decimal("1.05")]
    assert chain_linked_twr(factors) == Decimal("1.10") * Decimal("0.90") * Decimal("1.05")


# --- twr_summary ------------------------------------------------------------


def test_twr_constant_growth_golden() -> None:
    # 1% per day for 3 days, no flows: cumulative = 1.01^3.
    rows = [
        ("1000", "1010", "0"),
        ("1010", "1020.10", "0"),
        ("1020.10", "1030.301", "0"),
    ]
    summary = twr_summary(_series(rows))
    assert summary.cumulative_factor == Decimal("1.01") ** 3
    assert summary.cumulative_return == Decimal("1.01") ** 3 - 1
    assert summary.days == 3
    assert summary.annualized_return is None  # window shorter than 30 days
    assert summary.dormant_days == 0


def test_twr_flow_neutrality_golden() -> None:
    # A deposit doubling the portfolio mid-window must not change TWR.
    rows = [
        ("1000", "1100", "0"),  # +10%
        ("1100", "2200", "1100"),  # deposit, flat market
        ("2200", "2420", "0"),  # +10%
    ]
    summary = twr_summary(_series(rows))
    assert summary.cumulative_factor == Decimal("1.21")


def test_twr_funding_day_uses_flow_denominator() -> None:
    # First day of a funded account: MV_0 = F_0 means a flat day.
    rows = [("0", "1000", "1000"), ("1000", "1050", "0")]
    summary = twr_summary(_series(rows))
    assert summary.cumulative_factor == Decimal("1.05")


def test_twr_dormant_days_are_skipped() -> None:
    rows = [
        ("0", "0", "0"),
        ("0", "1000", "1000"),
        ("1000", "1100", "0"),
    ]
    summary = twr_summary(_series(rows))
    assert summary.dormant_days == 1
    assert summary.cumulative_factor == Decimal("1.1")


def test_twr_annualized_for_long_windows() -> None:
    n = MIN_ANNUALIZE_DAYS
    rows = [("1000", "1000", "0")] * n
    points = _series(rows)
    summary = twr_summary(points)
    assert summary.days == n
    assert summary.annualized_return == pytest.approx(0.0)


def test_twr_empty_series_raises() -> None:
    with pytest.raises(ReturnsError, match="empty series"):
        twr_summary([])


def test_twr_out_of_order_raises() -> None:
    points = _series([("1000", "1010", "0"), ("1010", "1020", "0")])
    with pytest.raises(ReturnsError, match="out of order"):
        twr_summary([points[1], points[0]])


def test_twr_discontinuous_values_raise() -> None:
    points = [
        ReturnPoint(as_of=_D0, begin_value=Decimal("1000"), end_value=Decimal("1010")),
        ReturnPoint(
            as_of=_D0 + timedelta(days=1),
            begin_value=Decimal("999"),
            end_value=Decimal("1000"),
        ),
    ]
    with pytest.raises(ReturnsError, match="discontinuous"):
        twr_summary(points)


def test_twr_data_gap_raises() -> None:
    # Value appears without a flow: must refuse, not fabricate.
    points = [
        ReturnPoint(as_of=_D0, begin_value=Decimal("0"), end_value=Decimal("0")),
        ReturnPoint(
            as_of=_D0 + timedelta(days=1),
            begin_value=Decimal("0"),
            end_value=Decimal("500"),
        ),
    ]
    with pytest.raises(ReturnsError, match="data gap"):
        twr_summary(points)


# --- xirr -------------------------------------------------------------------


def test_xirr_known_annual_return_golden() -> None:
    # Invest 1000, receive 1100 exactly 365 days later. With the
    # actual/365.25 convention the rate is (1.1)^(365.25/365) - 1.
    flows = [
        (_D0, Decimal("-1000")),
        (_D0 + timedelta(days=365), Decimal("1100")),
    ]
    result = xirr(flows)
    assert result is not None
    # 365 days vs 365.25-day year: (1.1)^(365.25/365) - 1
    assert result == pytest.approx(1.1 ** (365.25 / 365) - 1, abs=1e-9)


def test_xirr_zero_return_golden() -> None:
    flows = [(_D0, Decimal("-1000")), (_D0 + timedelta(days=200), Decimal("1000"))]
    assert xirr(flows) == pytest.approx(0.0, abs=1e-9)


def test_xirr_loss_golden() -> None:
    flows = [(_D0, Decimal("-1000")), (_D0 + timedelta(days=365), Decimal("500"))]
    result = xirr(flows)
    assert result is not None
    assert result == pytest.approx(0.5 ** (365.25 / 365) - 1, abs=1e-9)


def test_xirr_one_signed_flows_have_no_solution() -> None:
    assert xirr([(_D0, Decimal("-1")), (_D0 + timedelta(days=1), Decimal("-1"))]) is None
    assert xirr([(_D0, Decimal("1")), (_D0 + timedelta(days=1), Decimal("1"))]) is None


def test_xirr_fewer_than_two_nonzero_flows() -> None:
    assert xirr([]) is None
    assert xirr([(_D0, Decimal("-1000"))]) is None
    assert xirr([(_D0, Decimal("-1000")), (_D0, Decimal("0"))]) is None


def test_xirr_multi_flow_npv_root() -> None:
    flows = [
        (_D0, Decimal("-1000")),
        (_D0 + timedelta(days=120), Decimal("-500")),
        (_D0 + timedelta(days=300), Decimal("200")),
        (_D0 + timedelta(days=730), Decimal("1500")),
    ]
    rate = xirr(flows)
    assert rate is not None
    # The returned rate must zero the NPV.
    npv = sum(float(amount) / (1 + rate) ** ((d - _D0).days / 365.25) for d, amount in flows)
    assert npv == pytest.approx(0.0, abs=1e-6)


# --- mwr_from_series --------------------------------------------------------


def test_mwr_equals_twr_without_flows() -> None:
    # One year of flat-then-jump growth, no external flows: MWR == TWR.
    rows = [("1000", "1000", "0")] * 364 + [("1000", "1100", "0")]
    points = _series(rows)
    summary = twr_summary(points)
    mwr = mwr_from_series(points)
    assert mwr is not None
    assert summary.annualized_return is not None
    assert mwr == pytest.approx(summary.annualized_return, rel=1e-3)


def test_mwr_weights_late_contribution() -> None:
    # +10% in the first half-year, then a huge deposit, then -10% in
    # the second half: TWR is -1% but MWR is clearly negative because
    # most of the money only saw the loss.
    rows = [("1000", "1000", "0")] * 182
    rows.append(("1000", "1100", "0"))  # +10%
    rows.append(("1100", "11100", "10000"))  # deposit, flat market
    rows.extend([("11100", "11100", "0")] * 180)
    rows.append(("11100", "9990", "0"))  # -10%
    points = _series(rows)
    twr = twr_summary(points).cumulative_return
    mwr = mwr_from_series(points)
    assert twr == Decimal("-0.01")
    assert mwr is not None
    assert mwr < -0.05


def test_mwr_short_window_without_root_is_none() -> None:
    # Over a 3-day span the annualized root lies far outside the
    # solver bracket; refusing with None beats fabricating a rate.
    rows = [
        ("1000", "1100", "0"),
        ("1100", "11100", "10000"),
        ("11100", "9990", "0"),
    ]
    assert mwr_from_series(_series(rows)) is None


def test_mwr_empty_series() -> None:
    assert mwr_from_series([]) is None


# --- property-based ---------------------------------------------------------

_FACTORS = st.lists(
    st.decimals(
        min_value=Decimal("0.5"),
        max_value=Decimal("2.0"),
        allow_nan=False,
        allow_infinity=False,
        places=6,
    ),
    min_size=1,
    max_size=40,
)


@settings(max_examples=200)
@given(_FACTORS)
def test_chain_link_is_associative(factors: list[Decimal]) -> None:
    split = len(factors) // 2
    left = chain_linked_twr(factors[:split])
    right = chain_linked_twr(factors[split:])
    # Equality up to Decimal-context rounding of long products.
    assert float(chain_linked_twr(factors)) == pytest.approx(float(left * right), rel=1e-20)


@settings(max_examples=200)
@given(
    st.lists(
        st.tuples(
            st.decimals(
                min_value=Decimal("-0.05"),
                max_value=Decimal("0.05"),
                allow_nan=False,
                allow_infinity=False,
                places=4,
            ),
            st.decimals(
                min_value=Decimal("0"),
                max_value=Decimal("500"),
                allow_nan=False,
                allow_infinity=False,
                places=2,
            ),
        ),
        min_size=1,
        max_size=30,
    )
)
def test_twr_is_flow_invariant(days: list[tuple[Decimal, Decimal]]) -> None:
    """TWR must depend only on daily rates, never on flow sizes."""

    def build(flows_scale: Decimal) -> list[ReturnPoint]:
        points: list[ReturnPoint] = []
        value = Decimal("1000")
        for i, (rate, flow) in enumerate(days):
            scaled_flow = flow * flows_scale
            begin = value
            end = (begin + scaled_flow) * (1 + rate)
            points.append(
                ReturnPoint(
                    as_of=_D0 + timedelta(days=i),
                    begin_value=begin,
                    end_value=end,
                    net_flow=scaled_flow,
                )
            )
            value = end
        return points

    with_flows = twr_summary(build(Decimal("1")))
    without_flows = twr_summary(build(Decimal("0")))
    assert with_flows.cumulative_factor == pytest.approx(without_flows.cumulative_factor)


@settings(max_examples=100)
@given(
    rate=st.floats(min_value=-0.5, max_value=2.0, allow_nan=False),
    principal=st.decimals(
        min_value=Decimal("100"),
        max_value=Decimal("100000"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
    days=st.integers(min_value=30, max_value=2000),
)
def test_xirr_round_trips_known_rate(rate: float, principal: Decimal, days: int) -> None:
    """xirr() must recover the rate that generated a two-flow series."""
    final = float(principal) * (1 + rate) ** (days / 365.25)
    flows = [(_D0, -principal), (_D0 + timedelta(days=days), Decimal(str(final)))]
    solved = xirr(flows)
    assert solved is not None
    assert solved == pytest.approx(rate, abs=1e-6)


def test_summary_model_is_frozen() -> None:
    summary = twr_summary(_series([("1000", "1010", "0")]))
    assert isinstance(summary, TwrSummary)
    with pytest.raises(pydantic.ValidationError):
        summary.days = 99
