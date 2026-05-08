"""Pure-function tests for the Sutor Bank Depotauszug parser.

Covers:

* synthesize_external_id determinism + namespacing,
* number / date / percent locale parsing,
* holdings rows decoding (EUR-only and USD price flavors),
* transactions rows decoding for each Sutor type,
* metadata extraction from the joined PDF text, and
* end-to-end ``parse_pdf`` against the synthetic test fixture.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from penge.ingest.growney import (
    PROVIDER,
    TXN_KIND_BUY,
    TXN_KIND_DEPOSIT,
    TXN_KIND_DIVIDEND,
    TXN_KIND_FEE,
    parse_holdings_rows,
    parse_pdf,
    parse_transactions_rows,
    synthesize_external_id,
)
from penge.ingest.growney.parser import (
    _parse_de_date,
    _parse_de_number,
    _parse_de_percent,
    _parse_metadata,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_depotauszug.pdf"


# --- low-level helpers -----------------------------------------------------


def test_provider_slug_is_growney() -> None:
    assert PROVIDER == "growney"


@pytest.mark.parametrize(  # type: ignore[untyped-decorator]  # pytest decorator is untyped under strict mypy
    ("raw", "expected"),
    [
        ("1.609,38", Decimal("1609.38")),
        ("0,6186", Decimal("0.6186")),
        ("-2,02", Decimal("-2.02")),
        ("50,00", Decimal("50.00")),
        ("-", None),
        (None, None),
        ("77,66 EUR", Decimal("77.66")),
    ],
)
def test_parse_de_number(raw: str | None, expected: Decimal | None) -> None:
    assert _parse_de_number(raw) == expected


def test_parse_de_date() -> None:
    assert _parse_de_date("05.01.2026") == date(2026, 1, 5)


@pytest.mark.parametrize(  # type: ignore[untyped-decorator]  # pytest decorator is untyped under strict mypy
    ("raw", "expected"),
    [
        ("4,99 %", Decimal("4.99")),
        ("10,15 %", Decimal("10.15")),
        ("not a percent", None),
        (None, None),
    ],
)
def test_parse_de_percent(raw: str | None, expected: Decimal | None) -> None:
    assert _parse_de_percent(raw) == expected


# --- synthesize_external_id ------------------------------------------------


def test_synthesize_external_id_is_deterministic() -> None:
    a = synthesize_external_id(
        depot_number="9999999999",
        bookkeeping_date=date(2026, 1, 5),
        value_date=date(2026, 1, 2),
        sutor_type="Kauf",
        isin="LU0629460675",
        quantity=Decimal("0.0148"),
        net_amount_eur=Decimal("-2.02"),
        description="Kauf UBS ETF - MSCI EMU Socially Resp.",
    )
    b = synthesize_external_id(
        depot_number="9999999999",
        bookkeeping_date=date(2026, 1, 5),
        value_date=date(2026, 1, 2),
        sutor_type="Kauf",
        isin="LU0629460675",
        quantity=Decimal("0.0148"),
        net_amount_eur=Decimal("-2.02"),
        description="Kauf UBS ETF - MSCI EMU Socially Resp.",
    )
    assert a == b
    assert a.startswith("growney:")
    assert len(a) == len("growney:") + 16


def test_synthesize_external_id_changes_when_amount_changes() -> None:
    a = synthesize_external_id(
        depot_number="9999999999",
        bookkeeping_date=date(2026, 1, 5),
        value_date=date(2026, 1, 2),
        sutor_type="Kauf",
        isin="LU0629460675",
        quantity=Decimal("0.0148"),
        net_amount_eur=Decimal("-2.02"),
        description="x",
    )
    b = synthesize_external_id(
        depot_number="9999999999",
        bookkeeping_date=date(2026, 1, 5),
        value_date=date(2026, 1, 2),
        sutor_type="Kauf",
        isin="LU0629460675",
        quantity=Decimal("0.0148"),
        net_amount_eur=Decimal("-2.03"),
        description="x",
    )
    assert a != b


# --- holdings --------------------------------------------------------------


def test_parse_holdings_rows_eur_and_usd_prices() -> None:
    rows = [
        # EUR price column
        [
            "iShares MSCI Europe SRI ETF dis",
            "IE00BGDPWW94",
            "Irland",
            "Wertpapierrechnung",
            "16,60 %",
            "36,9062",
            "Anteile",
            "7,1233",
            "EUR",
            "262,89 EUR",
        ],
        # USD price column with footnote marker
        [
            "iShares MSCI USA SRI UCITS ETF dis",
            "IE00BZ173T46",
            "Irland",
            "Wertpapierrechnung",
            "42,49 %",
            "70,1539",
            "Anteile",
            "11,5337",
            "US$*",
            "703,72 EUR",
        ],
    ]
    holdings = parse_holdings_rows(rows)
    assert len(holdings) == 2
    eur = holdings[0]
    assert eur.isin == "IE00BGDPWW94"
    assert eur.quantity == Decimal("36.9062")
    assert eur.price_currency == "EUR"
    assert eur.market_value_eur == Decimal("262.89")
    usd = holdings[1]
    assert usd.price_currency == "USD"
    assert usd.market_value_eur == Decimal("703.72")


def test_parse_holdings_rows_skips_section_labels() -> None:
    rows = [
        ["Fonds"],  # section divider Sutor injects
        ["* Währungskurs: 1,1498 US$"],  # footnote
        [
            "iShares MSCI Europe SRI ETF dis",
            "IE00BGDPWW94",
            "Irland",
            "Wertpapierrechnung",
            "16,60 %",
            "36,9062",
            "Anteile",
            "7,1233",
            "EUR",
            "262,89 EUR",
        ],
    ]
    holdings = parse_holdings_rows(rows)
    assert len(holdings) == 1
    assert holdings[0].isin == "IE00BGDPWW94"


# --- transactions ----------------------------------------------------------


def _txn_rows() -> list[list[str | None]]:
    return [
        # Einzahlung
        [
            "02.01.2026",
            "02.01.2026",
            "Einzahlung",
            "automatischer Lastschrifteinzug",
            "-",
            "-",
            "",
            "50,00",
            "",
            "",
            "",
        ],
        # Kauf in EUR
        [
            "05.01.2026",
            "02.01.2026\n11:16",
            "Kauf\nTradegate",
            "Kauf UBS ETF - MSCI EMU Socially Resp.\nLU0629460675",
            "0,0148\n136,0400",
            "EUR",
            "",
            "-2,02",
            "",
            "",
            "",
        ],
        # Kauf with USD unit price + EUR/USD FX rate on W-Kurs column
        [
            "05.01.2026",
            "02.01.2026\n12:51",
            "Kauf\nTradegate",
            "Kauf iShares MSCI USA SRI UCITS ETF dis\nIE00BZ173T46",
            "2,4378\n11,9671",
            "1,1721\nUS$",
            "",
            "-24,89",
            "",
            "",
            "",
        ],
        # Ausschüttung in USD with EUR net
        [
            "07.01.2026",
            "29.12.2025",
            "Ausschüttung",
            "Betrag der Ausschüttung iShares MSCI USA SRI UCITS ETF\nIE00BZ173T46",
            "-",
            "US$",
            "",
            "2,98",
            "",
            "",
            "",
        ],
        # Gebühr
        [
            "02.02.2026",
            "02.02.2026",
            "Gebühr",
            "Servicegebühr 01.10.2025 - 31.12.2025",
            "-",
            "-",
            "",
            "-1,24",
            "",
            "",
            "",
        ],
    ]


def test_parse_transactions_rows_kinds_and_fields() -> None:
    txns = parse_transactions_rows(_txn_rows())
    kinds = [t.kind for t in txns]
    assert kinds == [
        TXN_KIND_DEPOSIT,
        TXN_KIND_BUY,
        TXN_KIND_BUY,
        TXN_KIND_DIVIDEND,
        TXN_KIND_FEE,
    ]
    deposit = txns[0]
    assert deposit.bookkeeping_date == date(2026, 1, 2)
    assert deposit.value_date == date(2026, 1, 2)
    assert deposit.net_amount_eur == Decimal("50.00")
    assert deposit.isin is None
    eur_kauf = txns[1]
    assert eur_kauf.isin == "LU0629460675"
    assert eur_kauf.quantity == Decimal("0.0148")
    assert eur_kauf.unit_price == Decimal("136.0400")
    assert eur_kauf.unit_price_currency == "EUR"
    assert eur_kauf.fx_rate is None
    assert eur_kauf.net_amount_eur == Decimal("-2.02")
    assert eur_kauf.venue == "Tradegate"
    usd_kauf = txns[2]
    assert usd_kauf.unit_price_currency == "USD"
    assert usd_kauf.fx_rate == Decimal("1.1721")
    assert usd_kauf.net_amount_eur == Decimal("-24.89")
    div = txns[3]
    assert div.isin == "IE00BZ173T46"
    assert div.net_amount_eur == Decimal("2.98")
    assert div.unit_price_currency == "USD"
    fee = txns[4]
    assert fee.net_amount_eur == Decimal("-1.24")
    assert fee.isin is None


def test_parse_transactions_rows_skips_non_date_rows() -> None:
    rows: list[list[str | None]] = [
        ["Buchungs-", "Wertstellung", "Transaktion", "Umsatz", "", "", "", "", "", "", ""],
        ["datum", "", "Handelsplatz", "ISIN", "", "", "", "", "", "", ""],
        ["02.01.2026", "02.01.2026", "Einzahlung", "x", "-", "-", "", "50,00", "", "", ""],
    ]
    txns = parse_transactions_rows(rows)
    assert len(txns) == 1


def test_parse_transactions_rows_unknown_type_raises() -> None:
    rows = [
        [
            "02.01.2026",
            "02.01.2026",
            "Mystery",
            "x",
            "-",
            "-",
            "",
            "1,00",
            "",
            "",
            "",
        ]
    ]
    with pytest.raises(ValueError, match="unknown Sutor Transaktion"):
        parse_transactions_rows(rows)


# --- metadata --------------------------------------------------------------


def test_parse_metadata_extracts_strategy_depot_iban_and_dates() -> None:
    text = (
        '"growgreen100" Nr. 9999999999 / IBAN: DE00 2023 0800 9999 9999 99\n'
        "Aufstellung über Kundenfinanzinstrumente per 31.03.2026\n"
        "Umsätze vom 01.01.2026 bis 31.03.2026 in EUR\n"
    )
    m = _parse_metadata(text)
    assert m.strategy == "growgreen100"
    assert m.depot_number == "9999999999"
    assert m.iban == "DE00202308009999999999"
    assert m.as_of == date(2026, 3, 31)
    assert m.period_from == date(2026, 1, 1)
    assert m.period_to == date(2026, 3, 31)


# --- end-to-end ------------------------------------------------------------


@pytest.mark.skipif(  # type: ignore[untyped-decorator]  # pytest decorator is untyped under strict mypy
    not FIXTURE.exists(), reason="synthetic PDF fixture missing"
)
def test_parse_pdf_fixture_round_trip() -> None:
    da = parse_pdf(FIXTURE)
    assert da.depot_number == "9999999999"
    assert da.iban == "DE00202308009999999999"
    assert da.strategy == "growgreen100"
    assert da.as_of == date(2026, 3, 31)
    assert da.period_from == date(2026, 1, 1)
    assert da.period_to == date(2026, 3, 31)
    assert len(da.holdings) == 5
    assert len(da.transactions) == 5
    assert da.cash_balance_eur == Decimal("0")
    assert {h.isin for h in da.holdings} == {
        "LU0629460675",
        "LU0629460832",
        "IE00BGDPWW94",
        "IE00BZ173T46",
        "IE00BGDQ0T50",
    }
    kinds = {t.kind for t in da.transactions}
    assert kinds == {TXN_KIND_BUY, TXN_KIND_DEPOSIT, TXN_KIND_DIVIDEND, TXN_KIND_FEE}
