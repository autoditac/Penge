"""Tests for :mod:`penge.tax.de_vorab`."""

from __future__ import annotations

from decimal import Decimal

import pytest

from penge.tax.de_vorab import (
    ABGELT_RATE,
    BASISZINS_DE,
    TEILFREISTELLUNG_QUOTES,
    FundClassification,
    VorabError,
    VorabInput,
    compute_vorabpauschale,
    compute_vorabpauschale_many,
    to_markdown,
)
from penge.tax.lots import Money


def _eur(v: str | int) -> Money:
    return Money(amount=Decimal(str(v)), currency="EUR")


def _input(
    *,
    isin: str = "IE0000000001",
    year: int = 2024,
    classification: FundClassification = "equity",
    start: str = "10000",
    end: str = "11000",
    distributions: str = "0",
    months: int = 12,
) -> VorabInput:
    return VorabInput(
        isin=isin,
        tax_year=year,
        classification=classification,
        start_value=_eur(start),
        end_value=_eur(end),
        distributions=_eur(distributions),
        holding_months=months,
    )


def test_constants_round_trip() -> None:
    assert Decimal("0.26375") == ABGELT_RATE
    assert BASISZINS_DE[2024] == Decimal("0.0229")
    assert TEILFREISTELLUNG_QUOTES["equity"] == Decimal("0.30")


def test_simple_equity_etf_2024() -> None:
    # start 10 000, end 11 000, basiszins 2.29 %
    # basisertrag = 10 000 × 0.0229 × 0.7 = 160.30
    # vorabpauschale = min(160.30, 1000) = 160.30
    # taxable = 160.30 × 0.70 = 112.21
    # tax = 112.21 × 0.26375 = 29.60
    r = compute_vorabpauschale(_input())
    assert r.basisertrag.amount == Decimal("160.30")
    assert r.vorabpauschale.amount == Decimal("160.30")
    assert r.taxable.amount == Decimal("112.21")
    assert r.tax_due.amount == Decimal("29.60")
    assert r.basiszins == Decimal("0.0229")
    assert r.teilfreistellung_quote == Decimal("0.30")


def test_negative_basiszins_clamped_to_zero() -> None:
    r = compute_vorabpauschale(_input(year=2021))
    assert r.basiszins == Decimal("0.00")
    assert r.basisertrag.amount == Decimal("0.00")
    assert r.vorabpauschale.amount == Decimal("0.00")
    assert r.tax_due.amount == Decimal("0.00")


def test_capped_at_actual_increase() -> None:
    # huge start value but tiny end value → wertzuwachs caps the VP
    r = compute_vorabpauschale(_input(start="100000", end="100050", distributions="0", year=2024))
    # basisertrag = 100 000 × 0.0229 × 0.7 = 1 603, but wertzuwachs = 50 caps it
    assert r.wertzuwachs.amount == Decimal("50.00")
    assert r.vorabpauschale.amount == Decimal("50.00")


def test_loss_year_no_vorabpauschale() -> None:
    r = compute_vorabpauschale(_input(start="10000", end="9000"))
    assert r.wertzuwachs.amount == Decimal("-1000.00")
    assert r.vorabpauschale.amount == Decimal("0.00")
    assert r.tax_due.amount == Decimal("0.00")


def test_distributions_reduce_vorabpauschale() -> None:
    # basisertrag = 160.30, distributions = 200 → VP after dist = 0
    r = compute_vorabpauschale(_input(start="10000", end="11000", distributions="200"))
    assert r.vorabpauschale.amount == Decimal("0.00")
    assert r.tax_due.amount == Decimal("0.00")


def test_partial_holding_months_pro_rates() -> None:
    # 6 months → basisertrag halved
    r = compute_vorabpauschale(_input(months=6))
    assert r.basisertrag.amount == Decimal("80.15")


def test_teilfreistellung_quotes_per_classification() -> None:
    eq = compute_vorabpauschale(_input(classification="equity"))
    mix = compute_vorabpauschale(_input(classification="mixed"))
    other = compute_vorabpauschale(_input(classification="other"))
    re_ = compute_vorabpauschale(_input(classification="real_estate"))
    # taxable share: equity 70 %, mixed 85 %, other 100 %, real_estate 40 %
    assert eq.taxable.amount < mix.taxable.amount < other.taxable.amount
    assert re_.taxable.amount < eq.taxable.amount


def test_unknown_year_raises() -> None:
    with pytest.raises(VorabError, match="Basiszins"):
        compute_vorabpauschale(_input(year=1999))


def test_eur_only_guard_start() -> None:
    with pytest.raises(VorabError, match="EUR"):
        VorabInput(
            isin="IE0000000001",
            tax_year=2024,
            classification="equity",
            start_value=Money(amount=Decimal("100"), currency="DKK"),
            end_value=_eur("100"),
        )


def test_negative_start_rejected() -> None:
    with pytest.raises(VorabError, match="non-negative"):
        VorabInput(
            isin="IE0000000001",
            tax_year=2024,
            classification="equity",
            start_value=Money(amount=Decimal("-1"), currency="EUR"),
            end_value=_eur("100"),
        )


def test_compute_many_ordering() -> None:
    a = _input(isin="IE0000000001", start="10000", end="11000")
    b = _input(isin="DE0001234567", start="20000", end="21000")
    out = compute_vorabpauschale_many([a, b])
    assert [r.isin for r in out] == ["IE0000000001", "DE0001234567"]


def test_to_markdown_empty() -> None:
    out = to_markdown([])
    assert "Vorabpauschale" in out
    assert "Keine Positionen" in out


def test_to_markdown_with_rows_has_totals() -> None:
    rs = compute_vorabpauschale_many([_input(), _input(isin="DE0001234567")])
    md = to_markdown(rs)
    assert "IE0000000001" in md
    assert "DE0001234567" in md
    assert "Abgeltungsteuer" in md
    assert "29.60" in md  # per-row tax appears at least once


def test_module_re_exports() -> None:
    from penge import tax

    assert tax.compute_vorabpauschale is compute_vorabpauschale
    assert tax.BASISZINS_DE is BASISZINS_DE
    assert tax.TEILFREISTELLUNG_QUOTES is TEILFREISTELLUNG_QUOTES
