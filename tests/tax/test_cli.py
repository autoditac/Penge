"""Tests for :mod:`penge.tax.cli` (issue #49)."""

from __future__ import annotations

import io
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from penge.tax.cli import CliError, compute_tax_year, main


def test_empty_spec_returns_zero_report_per_jurisdiction() -> None:
    out = compute_tax_year(year=2024, currency="EUR", jurisdictions=["DK", "DE"], spec={})
    assert len(out) == 2
    dk, de = out
    assert dk["jurisdiction"] == "DK"
    assert dk["currency"] == "EUR"
    assert dk["line_items"] == []
    assert dk["summary"]["gross_capital_income"] == 0.0
    assert dk["summary"]["taxable_capital_income"] == 0.0
    assert de["jurisdiction"] == "DE"
    assert de["line_items"] == []
    assert de["summary"]["total_tax_due"] == 0.0


def test_dk_lager_line_and_summary() -> None:
    spec = {
        "dk": {
            "lager": [
                {
                    "account_id": "nordnet-1",
                    "isin": "DK0001234567",
                    "tax_year": 2024,
                    "start_market_value": "10000.00",
                    "end_market_value": "11500.00",
                    "buys": [{"cost": "0"}],
                    "sells": [],
                    "distributions": [{"amount": "200.00"}],
                }
            ]
        }
    }
    [report] = compute_tax_year(year=2024, currency="DKK", jurisdictions=["DK"], spec=spec)
    assert report["currency"] == "DKK"
    sources = [li["source"] for li in report["line_items"]]
    assert "lager:nordnet-1:DK0001234567" in sources
    # gain = 11500 - 10000 + 200 = 1700
    lager_row = next(li for li in report["line_items"] if li["category"] == "lager")
    assert lager_row["amount"] == 1700.0
    assert report["summary"]["gross_capital_income"] == 1700.0
    assert report["summary"]["taxable_capital_income"] == 1700.0


def test_dk_ask_account_aggregated_and_marked_withheld() -> None:
    spec = {
        "dk": {
            "ask": [
                {
                    "account_id": "ask-1",
                    "lager": [
                        {
                            "account_id": "ask-1",
                            "isin": "DK0001111111",
                            "tax_year": 2024,
                            "start_market_value": "1000",
                            "end_market_value": "1500",
                        }
                    ],
                }
            ]
        }
    }
    [report] = compute_tax_year(year=2024, currency="DKK", jurisdictions=["DK"], spec=spec)
    ask_rows = [li for li in report["line_items"] if li["category"].startswith("ask")]
    # one row for gain, one for tax_withheld
    assert any(li["category"] == "ask" for li in ask_rows)
    assert any(li["category"] == "ask_tax_withheld" for li in ask_rows)
    # ASK does not feed kapitalindkomst
    assert report["summary"]["gross_capital_income"] == 0.0
    # 17 % * 500 DKK = 85.00
    withheld = next(li for li in ask_rows if li["category"] == "ask_tax_withheld")
    assert withheld["amount"] == 85.0


def test_dk_pal_line_item_uses_pal_rate() -> None:
    spec = {
        "dk": {
            "pal": [
                {
                    "account_id": "pfa-1",
                    "tax_year": 2024,
                    "start_market_value": "1000",
                    "end_market_value": "2000",
                    "contributions": [{"amount": "0"}],
                    "withdrawals": [],
                }
            ]
        }
    }
    [report] = compute_tax_year(year=2024, currency="DKK", jurisdictions=["DK"], spec=spec)
    pal_withheld = next(li for li in report["line_items"] if li["category"] == "pal_tax_withheld")
    # PAL rate 15.3 % * 1000 = 153.00
    assert pal_withheld["amount"] == 153.0


def test_de_vorab_line_items() -> None:
    spec = {
        "de": {
            "vorab": [
                {
                    "isin": "DE0001234567",
                    "tax_year": 2024,
                    "classification": "equity",
                    "start_value": "10000",
                    "end_value": "11000",
                    "distributions": "0",
                }
            ]
        }
    }
    [report] = compute_tax_year(year=2024, currency="EUR", jurisdictions=["DE"], spec=spec)
    cats = {li["category"] for li in report["line_items"]}
    assert {"vorabpauschale", "vorab_taxable", "vorab_tax_due"} <= cats
    assert report["summary"]["total_tax_due"] >= 0


def test_currency_conversion_with_explicit_fx() -> None:
    spec = {
        "fx": {"DKK_to_EUR": "0.134"},
        "dk": {
            "lager": [
                {
                    "account_id": "n",
                    "isin": "DK0001234567",
                    "tax_year": 2024,
                    "start_market_value": "0",
                    "end_market_value": "1000",
                }
            ]
        },
    }
    [report] = compute_tax_year(year=2024, currency="EUR", jurisdictions=["DK"], spec=spec)
    # 1000 DKK * 0.134 = 134.00 EUR
    lager_row = next(li for li in report["line_items"] if li["category"] == "lager")
    assert lager_row["amount"] == pytest.approx(134.0)
    assert report["currency"] == "EUR"


def test_missing_fx_rate_for_required_conversion_raises() -> None:
    spec = {
        "dk": {
            "lager": [
                {
                    "account_id": "n",
                    "isin": "DK0001234567",
                    "tax_year": 2024,
                    "start_market_value": "0",
                    "end_market_value": "1000",
                }
            ]
        }
    }
    with pytest.raises(CliError, match="DKK_to_EUR"):
        compute_tax_year(year=2024, currency="EUR", jurisdictions=["DK"], spec=spec)


def test_only_year_matching_inputs_are_included() -> None:
    spec = {
        "dk": {
            "lager": [
                {
                    "account_id": "n",
                    "isin": "DK0001234567",
                    "tax_year": 2023,
                    "start_market_value": "0",
                    "end_market_value": "999",
                },
                {
                    "account_id": "n",
                    "isin": "DK0001234567",
                    "tax_year": 2024,
                    "start_market_value": "0",
                    "end_market_value": "100",
                },
            ]
        }
    }
    [report] = compute_tax_year(year=2024, currency="DKK", jurisdictions=["DK"], spec=spec)
    assert len(report["line_items"]) == 1
    assert report["line_items"][0]["amount"] == 100.0


def test_main_reads_stdin_and_emits_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = json.dumps(
        {
            "dk": {
                "lager": [
                    {
                        "account_id": "a",
                        "isin": "DK0001234567",
                        "tax_year": 2024,
                        "start_market_value": "0",
                        "end_market_value": "500",
                    }
                ]
            }
        }
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    rc = main(
        [
            "--year",
            "2024",
            "--currency",
            "DKK",
            "--jurisdictions",
            "DK",
            "--input",
            "-",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed[0]["jurisdiction"] == "DK"
    assert parsed[0]["summary"]["gross_capital_income"] == 500.0


def test_main_missing_input_file_returns_error(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "--year",
            "2024",
            "--currency",
            "DKK",
            "--jurisdictions",
            "DK",
            "--input",
            "/nonexistent/penge-tax-fixture.json",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "input file not found" in err


def test_main_default_path_treated_as_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Point PENGE_TAX_INPUTS_DIR at an empty dir so the default file
    # does not exist; the report should be a zero report, not an error.
    monkeypatch.setenv("PENGE_TAX_INPUTS_DIR", str(tmp_path))
    rc = main(["--year", "2024", "--currency", "DKK", "--jurisdictions", "DK,DE"])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert [r["jurisdiction"] for r in parsed] == ["DK", "DE"]
    assert all(r["line_items"] == [] for r in parsed)


def test_main_rejects_unknown_jurisdiction(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--year", "2024", "--currency", "EUR", "--jurisdictions", "US"])
    assert rc == 2
    assert "unknown jurisdiction" in capsys.readouterr().err


def test_main_rejects_invalid_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("{not json"))
    rc = main(
        [
            "--year",
            "2024",
            "--currency",
            "DKK",
            "--jurisdictions",
            "DK",
            "--input",
            "-",
        ]
    )
    assert rc == 2
    assert "valid JSON" in capsys.readouterr().err


def test_decimal_quantization_half_even() -> None:
    # 1000.005 → 1000.00 with ROUND_HALF_EVEN
    spec = {
        "dk": {
            "lager": [
                {
                    "account_id": "a",
                    "isin": "DK0001234567",
                    "tax_year": 2024,
                    "start_market_value": "0",
                    "end_market_value": "1000.005",
                }
            ]
        }
    }
    [report] = compute_tax_year(year=2024, currency="DKK", jurisdictions=["DK"], spec=spec)
    # Lager calculator already quantizes; just confirm round-trip
    val = Decimal(str(report["line_items"][0]["amount"]))
    assert val == Decimal("1000.00")
