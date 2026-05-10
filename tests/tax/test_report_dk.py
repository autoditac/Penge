"""Tests for :mod:`penge.tax.report_dk`."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from penge.tax.aktiesparekonto import AskTaxResult
from penge.tax.lager import LagerResult
from penge.tax.lots import Money, RealisedGain
from penge.tax.pal import PalResult
from penge.tax.report_dk import (
    SkatReport,
    SkatReportError,
    build_skat_report,
    to_csv,
    to_markdown,
)


def _dkk(v: str | int) -> Money:
    return Money(amount=Decimal(str(v)), currency="DKK")


def _lager(account: str, isin: str, year: int, gain: str) -> LagerResult:
    return LagerResult(
        account_id=account,
        isin=isin,
        tax_year=year,
        start_market_value=_dkk(0),
        end_market_value=_dkk(0),
        buys_total=_dkk(0),
        sells_total=_dkk(0),
        distributions_total=_dkk(0),
        gain=_dkk(gain),
    )


def _ask(account: str, year: int, gain: str, tax: str) -> AskTaxResult:
    return AskTaxResult(
        account_id=account,
        tax_year=year,
        gain=_dkk(gain),
        tax_due=_dkk(tax),
        loss_carry_forward=_dkk(0),
    )


def _pal(account: str, year: int, ret: str, tax: str) -> PalResult:
    return PalResult(
        account_id=account,
        tax_year=year,
        start_market_value=_dkk(0),
        end_market_value=_dkk(0),
        contributions_total=_dkk(0),
        withdrawals_total=_dkk(0),
        return_amount=_dkk(ret),
        tax_due=_dkk(tax),
        loss_carry_forward=_dkk(0),
    )


def _realised(account: str, isin: str, day: date, gain: str) -> RealisedGain:
    return RealisedGain(
        event_date=day,
        account_id=account,
        isin=isin,
        quantity=Decimal("1"),
        proceeds=_dkk("100"),
        cost_basis=_dkk(str(Decimal("100") - Decimal(gain))),
        gain=_dkk(gain),
    )


def test_empty_report_is_zero() -> None:
    r = build_skat_report(tax_year=2024)
    assert r.tax_year == 2024
    assert r.rows == ()
    assert r.gross_capital_income.amount == Decimal("0.00")
    assert r.taxable_capital_income.amount == Decimal("0.00")
    assert r.loss_carry_forward.amount == Decimal("0.00")


def test_lager_row_feeds_capital_income() -> None:
    r = build_skat_report(
        tax_year=2024,
        lager_results=[_lager("nordnet", "IE0000000001", 2024, "1000")],
    )
    assert len(r.rows) == 1
    row = r.rows[0]
    assert row.line_number == 1
    assert row.category == "lager"
    assert row.source_id == "lager:nordnet:IE0000000001"
    assert r.gross_capital_income.amount == Decimal("1000.00")
    assert r.taxable_capital_income.amount == Decimal("1000.00")


def test_ask_does_not_feed_capital_income_but_records_withholding() -> None:
    r = build_skat_report(
        tax_year=2024,
        ask_results=[_ask("ask-1", 2024, "5000", "850")],
    )
    assert r.gross_capital_income.amount == Decimal("0.00")
    assert r.tax_withheld_total.amount == Decimal("850.00")


def test_pal_does_not_feed_capital_income_but_records_withholding() -> None:
    r = build_skat_report(
        tax_year=2024,
        pal_results=[_pal("pfa-1", 2024, "10000", "1530")],
    )
    assert r.gross_capital_income.amount == Decimal("0.00")
    assert r.tax_withheld_total.amount == Decimal("1530.00")


def test_realised_gain_bucketed_by_event_year() -> None:
    in_year = _realised("n1", "IE0000000001", date(2024, 6, 1), "200")
    out_of_year = _realised("n1", "IE0000000001", date(2023, 6, 1), "999")
    r = build_skat_report(tax_year=2024, realised_gains=[in_year, out_of_year])
    assert len(r.rows) == 1
    assert r.rows[0].gain.amount == Decimal("200.00")


def test_prior_year_loss_carry_forward_offsets_gain() -> None:
    r = build_skat_report(
        tax_year=2024,
        lager_results=[_lager("a", "IE0000000001", 2024, "1000")],
        prior_loss_carry_forward=_dkk("400"),
    )
    assert r.taxable_capital_income.amount == Decimal("600.00")
    assert r.loss_carry_forward.amount == Decimal("0.00")


def test_loss_in_year_creates_carry_forward() -> None:
    r = build_skat_report(
        tax_year=2024,
        lager_results=[_lager("a", "IE0000000001", 2024, "-500")],
    )
    assert r.taxable_capital_income.amount == Decimal("0.00")
    assert r.loss_carry_forward.amount == Decimal("500.00")


def test_carry_forward_plus_loss_accumulates() -> None:
    r = build_skat_report(
        tax_year=2024,
        lager_results=[_lager("a", "IE0000000001", 2024, "-300")],
        prior_loss_carry_forward=_dkk("200"),
    )
    assert r.taxable_capital_income.amount == Decimal("0.00")
    assert r.loss_carry_forward.amount == Decimal("500.00")


def test_only_matching_year_included() -> None:
    r = build_skat_report(
        tax_year=2024,
        lager_results=[
            _lager("a", "IE0000000001", 2023, "999"),
            _lager("a", "IE0000000001", 2024, "100"),
        ],
    )
    assert len(r.rows) == 1
    assert r.rows[0].gain.amount == Decimal("100.00")


def test_line_numbers_are_sequential_across_categories() -> None:
    r = build_skat_report(
        tax_year=2024,
        lager_results=[_lager("a", "IE0000000001", 2024, "10")],
        ask_results=[_ask("ask-1", 2024, "20", "3")],
        pal_results=[_pal("pfa-1", 2024, "30", "5")],
        realised_gains=[_realised("a", "IE0000000001", date(2024, 1, 1), "40")],
    )
    assert [row.line_number for row in r.rows] == [1, 2, 3, 4]
    assert [row.category for row in r.rows] == ["lager", "ask", "pal", "realised"]


def test_to_csv_has_header_and_row_count_matches() -> None:
    r = build_skat_report(
        tax_year=2024,
        lager_results=[_lager("a", "IE0000000001", 2024, "100")],
    )
    out = to_csv(r)
    lines = out.strip().split("\n")
    assert lines[0].startswith("line_number,category,source_id")
    assert len(lines) == 2
    assert "lager:a:IE0000000001" in lines[1]
    assert "100.00" in lines[1]


def test_to_markdown_contains_totals_and_lines() -> None:
    r = build_skat_report(
        tax_year=2024,
        lager_results=[_lager("a", "IE0000000001", 2024, "1000")],
        pal_results=[_pal("pfa-1", 2024, "10000", "1530")],
    )
    md = to_markdown(r)
    assert "tax year 2024" in md
    assert "Taxable capital income" in md
    assert "1530.00" in md
    assert "lager:a:IE0000000001" in md


def test_prior_carry_forward_must_be_dkk() -> None:
    with pytest.raises(SkatReportError):
        build_skat_report(
            tax_year=2024,
            prior_loss_carry_forward=Money(amount=Decimal("10"), currency="EUR"),
        )


def test_prior_carry_forward_must_be_non_negative() -> None:
    with pytest.raises(SkatReportError):
        build_skat_report(
            tax_year=2024,
            prior_loss_carry_forward=Money(amount=Decimal("-1"), currency="DKK"),
        )


def test_realised_in_eur_rejected() -> None:
    bad = RealisedGain(
        event_date=date(2024, 1, 1),
        account_id="a",
        isin="IE0000000001",
        quantity=Decimal("1"),
        proceeds=Money(amount=Decimal("100"), currency="EUR"),
        cost_basis=Money(amount=Decimal("90"), currency="EUR"),
        gain=Money(amount=Decimal("10"), currency="EUR"),
    )
    with pytest.raises(SkatReportError):
        build_skat_report(tax_year=2024, realised_gains=[bad])


def test_skat_report_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    r = build_skat_report(tax_year=2024)
    with pytest.raises(FrozenInstanceError):
        r.tax_year = 2025  # type: ignore[misc]


def test_round_trip_via_module_exports() -> None:
    from penge import tax

    assert tax.SkatReport is SkatReport
    assert tax.build_skat_report is build_skat_report
    assert tax.to_csv is to_csv
    assert tax.to_markdown is to_markdown
