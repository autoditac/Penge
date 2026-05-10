"""Tests for :mod:`penge.tax.aktiesparekonto` (DK ASK 17 % wrapper)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from penge.tax.aktiesparekonto import (
    ASK_DEPOSIT_CAPS,
    ASK_RATE,
    AskDeposit,
    AskError,
    check_deposit_cap,
    compute_ask_tax,
    compute_ask_taxes,
)
from penge.tax.lager import LagerInput, LagerResult, compute_lager
from penge.tax.lots import Money


def _dkk(amount: str | int) -> Money:
    return Money(amount=Decimal(str(amount)), currency="DKK")


def _eur(amount: str) -> Money:
    return Money(amount=Decimal(amount), currency="EUR")


def _lager(account_id: str, isin: str, year: int, start: int, end: int) -> LagerResult:
    return compute_lager(
        LagerInput(
            account_id=account_id,
            isin=isin,
            tax_year=year,
            start_market_value=_dkk(start),
            end_market_value=_dkk(end),
        )
    )


# ---------------------------------------------------------------------------
# Rate constant
# ---------------------------------------------------------------------------


def test_ask_rate_is_seventeen_percent() -> None:
    assert Decimal("0.17") == ASK_RATE


# ---------------------------------------------------------------------------
# compute_ask_tax / compute_ask_taxes
# ---------------------------------------------------------------------------


def test_single_isin_gain_taxed_at_17pct() -> None:
    res = compute_ask_tax(
        account_id="ask-1",
        lager_result=_lager("ask-1", "IE0000000001", 2024, 100000, 110000),
    )
    # gain 10 000, tax = 1700.00
    assert res.gain == _dkk("10000.00")
    assert res.tax_due == _dkk("1700.00")
    assert res.loss_carry_forward == _dkk("0.00")


def test_loss_yields_zero_tax_and_carry_forward() -> None:
    res = compute_ask_tax(
        account_id="ask-1",
        lager_result=_lager("ask-1", "IE0000000001", 2024, 100000, 80000),
    )
    assert res.gain == _dkk("-20000.00")
    assert res.tax_due == _dkk("0.00")
    assert res.loss_carry_forward == _dkk("20000.00")


def test_multiple_isins_net_within_year() -> None:
    """Loss on one ISIN must offset gain on another in the same year/account."""

    res = compute_ask_taxes(
        account_id="ask-1",
        tax_year=2024,
        lager_results=[
            _lager("ask-1", "IE0000000001", 2024, 100000, 130000),  # +30 000
            _lager("ask-1", "IE0000000002", 2024, 50000, 40000),  # -10 000
        ],
    )
    # net gain 20 000, tax = 3400
    assert res.gain == _dkk("20000.00")
    assert res.tax_due == _dkk("3400.00")
    assert res.loss_carry_forward == _dkk("0.00")


def test_mixed_account_id_rejected() -> None:
    with pytest.raises(AskError, match="account"):
        compute_ask_taxes(
            account_id="ask-1",
            tax_year=2024,
            lager_results=[_lager("ask-2", "IE0000000001", 2024, 0, 0)],
        )


def test_mixed_year_rejected() -> None:
    with pytest.raises(AskError, match="tax year"):
        compute_ask_taxes(
            account_id="ask-1",
            tax_year=2024,
            lager_results=[_lager("ask-1", "IE0000000001", 2025, 0, 0)],
        )


def test_empty_results_yields_zero_tax() -> None:
    res = compute_ask_taxes(
        account_id="ask-1",
        tax_year=2024,
        lager_results=[],
    )
    assert res.gain == _dkk("0.00")
    assert res.tax_due == _dkk("0.00")
    assert res.loss_carry_forward == _dkk("0.00")


# ---------------------------------------------------------------------------
# Deposit cap
# ---------------------------------------------------------------------------


def test_deposit_within_cap_is_ok() -> None:
    check_deposit_cap(
        account_id="ask-1",
        deposits=[
            AskDeposit(year=2024, amount=_dkk("100000")),
            AskDeposit(year=2024, amount=_dkk("35000")),
        ],
    )


def test_deposit_exceeding_cap_raises() -> None:
    with pytest.raises(AskError, match="exceed"):
        check_deposit_cap(
            account_id="ask-1",
            deposits=[
                AskDeposit(year=2024, amount=_dkk("100000")),
                AskDeposit(year=2024, amount=_dkk("36000")),
            ],
        )


def test_withdrawal_reopens_headroom() -> None:
    """Cumulative net deposit can be increased by an interim withdrawal."""

    check_deposit_cap(
        account_id="ask-1",
        deposits=[
            AskDeposit(year=2023, amount=_dkk("100000")),
            AskDeposit(year=2024, amount=_dkk("-50000")),
            AskDeposit(year=2024, amount=_dkk("80000")),
        ],
    )


def test_unknown_year_rejected() -> None:
    with pytest.raises(AskError, match="ASK_DEPOSIT_CAPS"):
        check_deposit_cap(
            account_id="ask-1",
            deposits=[AskDeposit(year=2099, amount=_dkk("1"))],
        )


def test_non_dkk_deposit_rejected() -> None:
    with pytest.raises(AskError):
        AskDeposit(year=2024, amount=_eur("100"))


def test_deposit_caps_table_is_monotonically_indexed_recently() -> None:
    """Sanity: 2020+ caps should be non-decreasing (SKAT only re-indexes upward)."""

    years = sorted(y for y in ASK_DEPOSIT_CAPS if y >= 2020)
    caps = [ASK_DEPOSIT_CAPS[y] for y in years]
    assert caps == sorted(caps)
