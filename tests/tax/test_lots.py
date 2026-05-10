"""Tests for penge.tax.lots — tax-lot tracker (gennemsnitsmetoden)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

import pydantic
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from penge.tax.lots import (
    Buy,
    LotBook,
    LotError,
    Merge,
    Money,
    RealisedGain,
    Sell,
    Split,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ISIN_A = "DK0010000001"
ISIN_B = "DK0010000002"
ISIN_C = "DK0010000003"
ACC = "nordnet-1"
EUR: Literal["EUR"] = "EUR"
DKK: Literal["DKK"] = "DKK"


def _eur(amount: str) -> Money:
    return Money(amount=Decimal(amount), currency=EUR)


def _dkk(amount: str) -> Money:
    return Money(amount=Decimal(amount), currency=DKK)


def _buy(
    qty: str,
    price: str,
    *,
    fee: str | None = None,
    currency: Literal["EUR", "DKK"] = EUR,
    isin: str = ISIN_A,
) -> Buy:
    return Buy(
        event_date=date(2024, 1, 1),
        account_id=ACC,
        isin=isin,
        quantity=Decimal(qty),
        price=Money(amount=Decimal(price), currency=currency),
        fee=Money(amount=Decimal(fee), currency=currency) if fee is not None else None,
    )


def _sell(
    qty: str,
    price: str,
    *,
    fee: str | None = None,
    currency: Literal["EUR", "DKK"] = EUR,
    isin: str = ISIN_A,
) -> Sell:
    return Sell(
        event_date=date(2024, 6, 1),
        account_id=ACC,
        isin=isin,
        quantity=Decimal(qty),
        price=Money(amount=Decimal(price), currency=currency),
        fee=Money(amount=Decimal(fee), currency=currency) if fee is not None else None,
    )


# ---------------------------------------------------------------------------
# Buy mechanics
# ---------------------------------------------------------------------------


class TestBuy:
    def test_single_buy_creates_lot(self) -> None:
        book = LotBook()
        book.apply(_buy("10", "100.00"))
        lot = book.lot(ACC, ISIN_A)
        assert lot is not None
        assert lot.quantity == Decimal("10.000000")
        assert lot.cost_basis.amount == Decimal("1000.00")
        assert lot.avg_cost == Decimal("100.00")

    def test_two_buys_blend_average_cost(self) -> None:
        book = LotBook()
        book.apply(_buy("10", "100.00"))
        book.apply(_buy("10", "120.00"))
        lot = book.lot(ACC, ISIN_A)
        assert lot is not None
        assert lot.quantity == Decimal("20.000000")
        assert lot.cost_basis.amount == Decimal("2200.00")
        assert lot.avg_cost == Decimal("110.00")

    def test_buy_fee_added_to_cost_basis(self) -> None:
        book = LotBook()
        book.apply(_buy("10", "100.00", fee="9.99"))
        lot = book.lot(ACC, ISIN_A)
        assert lot is not None
        assert lot.cost_basis.amount == Decimal("1009.99")

    def test_currency_mismatch_on_second_buy_rejected(self) -> None:
        book = LotBook()
        book.apply(_buy("10", "100.00", currency=EUR))
        with pytest.raises(LotError, match="currency mismatch"):
            book.apply(_buy("5", "100.00", currency=DKK))

    def test_negative_quantity_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="strictly positive"):
            _buy("-1", "100.00")

    def test_zero_quantity_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="strictly positive"):
            _buy("0", "100.00")

    def test_fee_currency_must_match_price(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="fee currency"):
            Buy(
                event_date=date(2024, 1, 1),
                account_id=ACC,
                isin=ISIN_A,
                quantity=Decimal("1"),
                price=_eur("100"),
                fee=_dkk("1"),
            )


# ---------------------------------------------------------------------------
# Sell mechanics — gennemsnitsmetoden
# ---------------------------------------------------------------------------


class TestSell:
    def test_partial_sell_uses_average_cost(self) -> None:
        book = LotBook()
        book.apply(_buy("10", "100.00"))
        book.apply(_buy("10", "120.00"))
        # Average is 110; sell 5 at 130 → gain = 5 * (130 - 110) = 100.
        book.apply(_sell("5", "130.00"))
        gains = book.realised_gains()
        assert len(gains) == 1
        assert gains[0].gain.amount == Decimal("100.00")
        assert gains[0].cost_basis.amount == Decimal("550.00")
        assert gains[0].proceeds.amount == Decimal("650.00")
        # Remaining lot keeps the (unchanged) average cost.
        lot = book.lot(ACC, ISIN_A)
        assert lot is not None
        assert lot.quantity == Decimal("15.000000")
        assert lot.avg_cost == Decimal("110.00")

    def test_full_sell_closes_lot(self) -> None:
        book = LotBook()
        book.apply(_buy("10", "100.00"))
        book.apply(_sell("10", "150.00"))
        assert book.lot(ACC, ISIN_A) is None
        assert book.realised_gains()[0].gain.amount == Decimal("500.00")

    def test_sell_loss_is_negative_gain(self) -> None:
        book = LotBook()
        book.apply(_buy("10", "200.00"))
        book.apply(_sell("4", "150.00"))
        assert book.realised_gains()[0].gain.amount == Decimal("-200.00")

    def test_sell_fee_reduces_proceeds(self) -> None:
        book = LotBook()
        book.apply(_buy("10", "100.00"))
        book.apply(_sell("10", "150.00", fee="20.00"))
        # proceeds = 10*150 - 20 = 1480; cost = 1000; gain = 480.
        assert book.realised_gains()[0].gain.amount == Decimal("480.00")

    def test_oversell_rejected(self) -> None:
        book = LotBook()
        book.apply(_buy("10", "100.00"))
        with pytest.raises(LotError, match="only"):
            book.apply(_sell("11", "100.00"))

    def test_sell_without_lot_rejected(self) -> None:
        book = LotBook()
        with pytest.raises(LotError, match="no open lot"):
            book.apply(_sell("1", "100.00"))


# ---------------------------------------------------------------------------
# Split / Merge
# ---------------------------------------------------------------------------


class TestSplit:
    def test_two_for_one_split_doubles_quantity_keeps_cost(self) -> None:
        book = LotBook()
        book.apply(_buy("10", "100.00"))
        book.apply(
            Split(
                event_date=date(2024, 3, 1),
                account_id=ACC,
                isin=ISIN_A,
                ratio=Decimal("2"),
            )
        )
        lot = book.lot(ACC, ISIN_A)
        assert lot is not None
        assert lot.quantity == Decimal("20.000000")
        assert lot.cost_basis.amount == Decimal("1000.00")
        assert lot.avg_cost == Decimal("50.00")

    def test_reverse_split_halves_quantity(self) -> None:
        book = LotBook()
        book.apply(_buy("10", "50.00"))
        book.apply(
            Split(
                event_date=date(2024, 3, 1),
                account_id=ACC,
                isin=ISIN_A,
                ratio=Decimal("0.5"),
            )
        )
        lot = book.lot(ACC, ISIN_A)
        assert lot is not None
        assert lot.quantity == Decimal("5.000000")
        assert lot.cost_basis.amount == Decimal("500.00")
        assert lot.avg_cost == Decimal("100.00")

    def test_split_without_lot_rejected(self) -> None:
        book = LotBook()
        with pytest.raises(LotError, match="cannot split"):
            book.apply(
                Split(
                    event_date=date(2024, 3, 1),
                    account_id=ACC,
                    isin=ISIN_A,
                    ratio=Decimal("2"),
                )
            )


class TestMerge:
    def test_merger_replaces_lot_and_preserves_cost(self) -> None:
        book = LotBook()
        book.apply(_buy("10", "100.00", isin=ISIN_A))
        book.apply(
            Merge(
                event_date=date(2024, 3, 1),
                account_id=ACC,
                isin=ISIN_A,
                new_isin=ISIN_B,
                share_ratio=Decimal("1.5"),
            )
        )
        assert book.lot(ACC, ISIN_A) is None
        new_lot = book.lot(ACC, ISIN_B)
        assert new_lot is not None
        assert new_lot.quantity == Decimal("15.000000")
        assert new_lot.cost_basis.amount == Decimal("1000.00")

    def test_merge_into_existing_lot_blends(self) -> None:
        book = LotBook()
        book.apply(_buy("10", "100.00", isin=ISIN_A))
        book.apply(_buy("5", "200.00", isin=ISIN_B))
        book.apply(
            Merge(
                event_date=date(2024, 3, 1),
                account_id=ACC,
                isin=ISIN_A,
                new_isin=ISIN_B,
                share_ratio=Decimal("1"),
            )
        )
        lot = book.lot(ACC, ISIN_B)
        assert lot is not None
        assert lot.quantity == Decimal("15.000000")
        # Cost = 1000 (from A) + 1000 (from B) = 2000; 2000/15 ≈ 133.33.
        assert lot.cost_basis.amount == Decimal("2000.00")


# ---------------------------------------------------------------------------
# Cross-validated worked example
# ---------------------------------------------------------------------------


class TestWorkedExample:
    """Hand-calculated example that verifies gennemsnitsmetoden end-to-end.

    Account A buys an ETF in three tranches, then sells in two. The
    average-cost method blends each buy into the running average before
    a sale uses that average as cost basis.

    Trades (all DKK):
      - Buy 100 @ 50  → cost 5000  → avg 50
      - Buy  50 @ 80  → cost 9000  → avg 60
      - Sell 60 @ 90  → gain = 60 * (90 - 60) = 1800; remaining 90 @ avg 60.
      - Buy  10 @ 70  → cost 90*60 + 10*70 = 6100; qty 100; avg 61.
      - Sell 100 @ 75 → gain = 100 * (75 - 61) = 1400; book empty.

    Total realised gain = 1800 + 1400 = 3200 DKK.
    """

    def test_dk_avg_cost_three_buys_two_sells(self) -> None:
        book = LotBook()
        book.apply(_buy("100", "50.00", currency=DKK))
        book.apply(_buy("50", "80.00", currency=DKK))
        book.apply(_sell("60", "90.00", currency=DKK))
        book.apply(_buy("10", "70.00", currency=DKK))
        book.apply(_sell("100", "75.00", currency=DKK))
        gains = book.realised_gains()
        assert len(gains) == 2
        assert gains[0].gain.amount == Decimal("1800.00")
        assert gains[1].gain.amount == Decimal("1400.00")
        total = sum((g.gain.amount for g in gains), start=Decimal("0"))
        assert total == Decimal("3200.00")
        assert book.lot(ACC, ISIN_A) is None


# ---------------------------------------------------------------------------
# Property-based invariants
# ---------------------------------------------------------------------------


@st.composite
def _trade_sequence(draw: st.DrawFn) -> list[Buy | Sell]:
    """Produce a sequence of buys/sells that never oversells.

    Generates plausibly noisy sizes/prices, skipping a sell whenever it
    would exceed the running quantity. Splits/merges are excluded here
    to keep the invariant focused on the core average-cost arithmetic.
    """
    n = draw(st.integers(min_value=1, max_value=12))
    qty = Decimal("0")
    seq: list[Buy | Sell] = []
    for _ in range(n):
        kind = draw(st.sampled_from(["buy", "sell"]))
        size_raw = draw(st.integers(min_value=1, max_value=1000))
        size = Decimal(size_raw)
        price = Decimal(str(draw(st.integers(min_value=1, max_value=10000)))) / Decimal("100")
        if kind == "buy" or qty == 0:
            seq.append(_buy(str(size), str(price)))
            qty += size
        else:
            sell_size = min(size, qty)
            if sell_size <= 0:
                continue
            seq.append(_sell(str(sell_size), str(price)))
            qty -= sell_size
    return seq


@settings(max_examples=80, deadline=None)
@given(_trade_sequence())
def test_invariant_quantity_equals_buys_minus_sells(seq: list[Buy | Sell]) -> None:
    """Sum of buy quantities minus sum of sell quantities equals lot quantity."""
    book = LotBook()
    book.apply_all(seq)
    expected = Decimal("0")
    for ev in seq:
        if isinstance(ev, Buy):
            expected += ev.quantity
        else:
            expected -= ev.quantity
    assert book.total_quantity(ACC, ISIN_A) == expected.quantize(Decimal("0.000001"))


@settings(max_examples=80, deadline=None)
@given(_trade_sequence())
def test_invariant_cost_basis_consistent_with_realised(seq: list[Buy | Sell]) -> None:
    """Total contributed cost = remaining cost basis + total realised cost basis."""
    book = LotBook()
    book.apply_all(seq)
    contributed = sum(
        (ev.quantity * ev.price.amount for ev in seq if isinstance(ev, Buy)),
        start=Decimal("0"),
    )
    remaining_lot = book.lot(ACC, ISIN_A)
    remaining = remaining_lot.cost_basis.amount if remaining_lot is not None else Decimal("0")
    realised_cost = sum(
        (g.cost_basis.amount for g in book.realised_gains()),
        start=Decimal("0"),
    )
    diff = contributed - (remaining + realised_cost)
    # Allow a tiny rounding crumb (1 DKK cent per realised gain at most).
    tolerance = Decimal("0.01") * (len(book.realised_gains()) + 1)
    assert abs(diff) <= tolerance


# ---------------------------------------------------------------------------
# Realised-gain output type
# ---------------------------------------------------------------------------


def test_realised_gain_currency_consistency_enforced() -> None:
    with pytest.raises(pydantic.ValidationError, match="share a currency"):
        RealisedGain(
            event_date=date(2024, 1, 1),
            account_id=ACC,
            isin=ISIN_A,
            quantity=Decimal("1"),
            proceeds=Money(amount=Decimal("100"), currency=EUR),
            cost_basis=Money(amount=Decimal("90"), currency=DKK),
            gain=Money(amount=Decimal("10"), currency=EUR),
        )


def test_money_rejects_nan() -> None:
    with pytest.raises(pydantic.ValidationError, match="finite"):
        Money(amount=Decimal("NaN"), currency=EUR)


def test_isin_length_validated() -> None:
    with pytest.raises(pydantic.ValidationError):
        Buy(
            event_date=date(2024, 1, 1),
            account_id=ACC,
            isin="too-short",
            quantity=Decimal("1"),
            price=_eur("100"),
        )


def test_unrelated_pairs_kept_separate() -> None:
    """Lots are keyed by (account_id, isin) and don't bleed into each other."""
    book = LotBook()
    book.apply(_buy("10", "100.00", isin=ISIN_A))
    book.apply(_buy("5", "200.00", isin=ISIN_C))
    a = book.lot(ACC, ISIN_A)
    c = book.lot(ACC, ISIN_C)
    assert a is not None and c is not None
    assert a.cost_basis.amount == Decimal("1000.00")
    assert c.cost_basis.amount == Decimal("1000.00")
    assert len(book.lots()) == 2
