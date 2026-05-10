"""Tests for :mod:`penge.tax.lager` (DK lagerbeskatning calculator)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from penge.tax.lager import (
    BuyLeg,
    Distribution,
    LagerError,
    LagerInput,
    SellLeg,
    compute_lager,
    compute_lager_many,
    sum_gain_by_year,
)
from penge.tax.lots import Money


def _dkk(amount: str | int | Decimal) -> Money:
    return Money(amount=Decimal(str(amount)), currency="DKK")


def _eur(amount: str) -> Money:
    return Money(amount=Decimal(amount), currency="EUR")


# ---------------------------------------------------------------------------
# Worked example (matches docs/tax/dk.md narrative)
# ---------------------------------------------------------------------------


def test_worked_example_simple_appreciation() -> None:
    """100 k DKK ETF appreciates to 110 k DKK over the year, no trades."""

    inp = LagerInput(
        account_id="acc-1",
        isin="IE00B4L5Y983",
        tax_year=2024,
        start_market_value=_dkk("100000"),
        end_market_value=_dkk("110000"),
    )
    res = compute_lager(inp)
    assert res.gain == _dkk("10000.00")


def test_worked_example_with_trades_and_distribution() -> None:
    """Mid-year buy + sell + distribution.

    Hand-calculated:
      start MV  : 50 000
      end MV    : 80 000
      buy       : 20 000
      sell      :  5 000
      dist      :    500
      gain = 80 000 - 50 000 - 20 000 + 5 000 + 500 = 15 500
    """

    inp = LagerInput(
        account_id="acc-1",
        isin="IE00B4L5Y983",
        tax_year=2024,
        start_market_value=_dkk("50000"),
        end_market_value=_dkk("80000"),
        buys=(BuyLeg(cost=_dkk("20000")),),
        sells=(SellLeg(proceeds=_dkk("5000")),),
        distributions=(Distribution(amount=_dkk("500")),),
    )
    res = compute_lager(inp)
    assert res.gain == _dkk("15500.00")
    assert res.buys_total == _dkk("20000.00")
    assert res.sells_total == _dkk("5000.00")
    assert res.distributions_total == _dkk("500.00")


def test_loss_is_negative() -> None:
    inp = LagerInput(
        account_id="acc",
        isin="IE0",
        tax_year=2024,
        start_market_value=_dkk("100000"),
        end_market_value=_dkk("85000"),
    )
    assert compute_lager(inp).gain == _dkk("-15000.00")


def test_full_exit_during_year() -> None:
    """Bought start of year for 10k, sold during year for 12k, end MV = 0."""

    inp = LagerInput(
        account_id="acc",
        isin="IE0",
        tax_year=2024,
        start_market_value=_dkk("10000"),
        end_market_value=_dkk("0"),
        sells=(SellLeg(proceeds=_dkk("12000")),),
    )
    assert compute_lager(inp).gain == _dkk("2000.00")


def test_multiple_buys_and_sells_aggregate() -> None:
    inp = LagerInput(
        account_id="acc",
        isin="IE0",
        tax_year=2024,
        start_market_value=_dkk("0"),
        end_market_value=_dkk("30000"),
        buys=(BuyLeg(cost=_dkk("10000")), BuyLeg(cost=_dkk("15000"))),
        sells=(SellLeg(proceeds=_dkk("2000")), SellLeg(proceeds=_dkk("1000"))),
    )
    res = compute_lager(inp)
    # 30000 - 0 - 25000 + 3000 = 8000
    assert res.gain == _dkk("8000.00")
    assert res.buys_total == _dkk("25000.00")
    assert res.sells_total == _dkk("3000.00")


# ---------------------------------------------------------------------------
# Currency / validation guardrails
# ---------------------------------------------------------------------------


def test_non_dkk_market_value_rejected() -> None:
    with pytest.raises(LagerError):
        LagerInput(
            account_id="acc",
            isin="IE0",
            tax_year=2024,
            start_market_value=_eur("100"),
            end_market_value=_dkk("100"),
        )


def test_non_dkk_buy_rejected() -> None:
    with pytest.raises(LagerError):
        BuyLeg(cost=_eur("100"))


def test_non_dkk_sell_rejected() -> None:
    with pytest.raises(LagerError):
        SellLeg(proceeds=_eur("100"))


def test_non_dkk_distribution_rejected() -> None:
    with pytest.raises(LagerError):
        Distribution(amount=_eur("100"))


def test_negative_buy_rejected() -> None:
    with pytest.raises(LagerError):
        BuyLeg(cost=_dkk("-1"))


def test_negative_market_value_rejected() -> None:
    with pytest.raises(LagerError):
        LagerInput(
            account_id="acc",
            isin="IE0",
            tax_year=2024,
            start_market_value=_dkk("-1"),
            end_market_value=_dkk("100"),
        )


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def test_compute_lager_many_preserves_order() -> None:
    inputs = [
        LagerInput(
            account_id="a",
            isin=f"IE{i}",
            tax_year=2024,
            start_market_value=_dkk("0"),
            end_market_value=_dkk(str(i * 100)),
        )
        for i in range(5)
    ]
    results = compute_lager_many(inputs)
    assert [r.isin for r in results] == [f"IE{i}" for i in range(5)]


def test_sum_gain_by_year() -> None:
    results = compute_lager_many(
        [
            LagerInput(
                account_id="a",
                isin="IE1",
                tax_year=2024,
                start_market_value=_dkk("0"),
                end_market_value=_dkk("1000"),
            ),
            LagerInput(
                account_id="a",
                isin="IE2",
                tax_year=2024,
                start_market_value=_dkk("0"),
                end_market_value=_dkk("2000"),
            ),
            LagerInput(
                account_id="a",
                isin="IE1",
                tax_year=2025,
                start_market_value=_dkk("1000"),
                end_market_value=_dkk("1500"),
            ),
        ]
    )
    totals = sum_gain_by_year(results)
    assert totals[2024] == _dkk("3000.00")
    assert totals[2025] == _dkk("500.00")


# ---------------------------------------------------------------------------
# Property: gain definition is linear in each component
# ---------------------------------------------------------------------------


_amount = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("10000000"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)


@settings(max_examples=100, deadline=None)
@given(
    start_mv=_amount,
    end_mv=_amount,
    buy_amounts=st.lists(_amount, max_size=5),
    sell_amounts=st.lists(_amount, max_size=5),
    dist_amounts=st.lists(_amount, max_size=5),
)
def test_gain_formula_property(
    start_mv: Decimal,
    end_mv: Decimal,
    buy_amounts: list[Decimal],
    sell_amounts: list[Decimal],
    dist_amounts: list[Decimal],
) -> None:
    inp = LagerInput(
        account_id="a",
        isin="IE0",
        tax_year=2024,
        start_market_value=Money(amount=start_mv, currency="DKK"),
        end_market_value=Money(amount=end_mv, currency="DKK"),
        buys=tuple(BuyLeg(cost=Money(amount=a, currency="DKK")) for a in buy_amounts),
        sells=tuple(SellLeg(proceeds=Money(amount=a, currency="DKK")) for a in sell_amounts),
        distributions=tuple(
            Distribution(amount=Money(amount=a, currency="DKK")) for a in dist_amounts
        ),
    )
    res = compute_lager(inp)
    expected = (
        end_mv
        - start_mv
        - sum(buy_amounts, Decimal("0"))
        + sum(sell_amounts, Decimal("0"))
        + sum(dist_amounts, Decimal("0"))
    )
    assert res.gain.amount == expected.quantize(Decimal("0.01"))


@settings(max_examples=50, deadline=None)
@given(
    start_mv=_amount,
    end_mv=_amount,
)
def test_no_trades_no_dist_is_pure_appreciation(
    start_mv: Decimal,
    end_mv: Decimal,
) -> None:
    inp = LagerInput(
        account_id="a",
        isin="IE0",
        tax_year=2024,
        start_market_value=Money(amount=start_mv, currency="DKK"),
        end_market_value=Money(amount=end_mv, currency="DKK"),
    )
    assert compute_lager(inp).gain.amount == (end_mv - start_mv).quantize(Decimal("0.01"))
