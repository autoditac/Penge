"""Tests for :mod:`penge.tax.pal` (DK PAL-skat 15.3 % pension yield tax)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from penge.tax.lots import Money
from penge.tax.pal import (
    PAL_RATE,
    PalContribution,
    PalError,
    PalInput,
    PalWithdrawal,
    compute_pal,
    compute_pal_many,
)


def _dkk(amount: str | int) -> Money:
    return Money(amount=Decimal(str(amount)), currency="DKK")


def _eur(amount: str) -> Money:
    return Money(amount=Decimal(amount), currency="EUR")


def test_pal_rate_is_15_3pct() -> None:
    assert Decimal("0.153") == PAL_RATE


# ---------------------------------------------------------------------------
# Worked examples
# ---------------------------------------------------------------------------


def test_simple_appreciation_taxed_at_153pct() -> None:
    inp = PalInput(
        account_id="pfa-1",
        tax_year=2024,
        start_market_value=_dkk("500000"),
        end_market_value=_dkk("550000"),
    )
    res = compute_pal(inp)
    # return = 50_000, tax = 50_000 * 0.153 = 7_650.00
    assert res.return_amount == _dkk("50000.00")
    assert res.tax_due == _dkk("7650.00")
    assert res.loss_carry_forward == _dkk("0.00")


def test_loss_yields_zero_tax_and_carry_forward() -> None:
    inp = PalInput(
        account_id="pfa-1",
        tax_year=2024,
        start_market_value=_dkk("500000"),
        end_market_value=_dkk("470000"),
    )
    res = compute_pal(inp)
    assert res.return_amount == _dkk("-30000.00")
    assert res.tax_due == _dkk("0.00")
    assert res.loss_carry_forward == _dkk("30000.00")


def test_contribution_does_not_inflate_return() -> None:
    """A 50 k contribution mid-year that lifts MV by 50 k must yield zero return."""

    inp = PalInput(
        account_id="pfa-1",
        tax_year=2024,
        start_market_value=_dkk("500000"),
        end_market_value=_dkk("550000"),
        contributions=(PalContribution(amount=_dkk("50000")),),
    )
    res = compute_pal(inp)
    assert res.return_amount == _dkk("0.00")
    assert res.tax_due == _dkk("0.00")


def test_withdrawal_does_not_deflate_return() -> None:
    """A 30 k withdrawal mid-year that depressed MV by 30 k must yield zero return."""

    inp = PalInput(
        account_id="pfa-1",
        tax_year=2024,
        start_market_value=_dkk("500000"),
        end_market_value=_dkk("470000"),
        withdrawals=(PalWithdrawal(amount=_dkk("30000")),),
    )
    res = compute_pal(inp)
    assert res.return_amount == _dkk("0.00")
    assert res.tax_due == _dkk("0.00")


def test_full_formula_combination() -> None:
    """end - start - Σcontribs + Σwithdrawals.

    start = 500 000, end = 600 000, contribs = 30 000, withdrawals = 10 000
    return = 600 000 - 500 000 - 30 000 + 10 000 = 80 000
    tax    = 80 000 * 0.153 = 12 240
    """

    inp = PalInput(
        account_id="pfa-1",
        tax_year=2024,
        start_market_value=_dkk("500000"),
        end_market_value=_dkk("600000"),
        contributions=(
            PalContribution(amount=_dkk("20000")),
            PalContribution(amount=_dkk("10000")),
        ),
        withdrawals=(PalWithdrawal(amount=_dkk("10000")),),
    )
    res = compute_pal(inp)
    assert res.return_amount == _dkk("80000.00")
    assert res.tax_due == _dkk("12240.00")
    assert res.contributions_total == _dkk("30000.00")
    assert res.withdrawals_total == _dkk("10000.00")


def test_zero_balance_account_yields_zero_everything() -> None:
    inp = PalInput(
        account_id="pfa-1",
        tax_year=2024,
        start_market_value=_dkk("0"),
        end_market_value=_dkk("0"),
    )
    res = compute_pal(inp)
    assert res.return_amount == _dkk("0.00")
    assert res.tax_due == _dkk("0.00")
    assert res.loss_carry_forward == _dkk("0.00")


# ---------------------------------------------------------------------------
# Validation guardrails
# ---------------------------------------------------------------------------


def test_non_dkk_market_value_rejected() -> None:
    with pytest.raises(PalError):
        PalInput(
            account_id="pfa-1",
            tax_year=2024,
            start_market_value=_eur("100"),
            end_market_value=_dkk("100"),
        )


def test_non_dkk_contribution_rejected() -> None:
    with pytest.raises(PalError):
        PalContribution(amount=_eur("100"))


def test_non_dkk_withdrawal_rejected() -> None:
    with pytest.raises(PalError):
        PalWithdrawal(amount=_eur("100"))


def test_negative_contribution_rejected() -> None:
    with pytest.raises(PalError):
        PalContribution(amount=_dkk("-1"))


def test_negative_market_value_rejected() -> None:
    with pytest.raises(PalError):
        PalInput(
            account_id="pfa-1",
            tax_year=2024,
            start_market_value=_dkk("-1"),
            end_market_value=_dkk("100"),
        )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def test_compute_pal_many_preserves_order() -> None:
    inputs = [
        PalInput(
            account_id=f"pfa-{i}",
            tax_year=2024,
            start_market_value=_dkk("0"),
            end_market_value=_dkk(str(i * 1000)),
        )
        for i in range(4)
    ]
    out = compute_pal_many(inputs)
    assert [r.account_id for r in out] == [f"pfa-{i}" for i in range(4)]
