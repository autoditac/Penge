"""Tests for the PFA Pensionsoversigt parser.

Covers:

* synthesize_external_id determinism + namespacing,
* Danish number/date/percent locale parsing,
* contribution-source classification,
* holdings rows decoding (skipping ``I alt`` totals),
* scheme-summary rows decoding for the canonical PFA schemes,
* metadata extraction from the joined PDF text,
* end-to-end ``parse_pensionsoversigt`` against the synthetic
  text-embedded fixture, and
* OCR fallback path against a scanned-image fixture (with
  pytesseract mocked because Danish language data may not be
  available on the CI runner).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pytest

from penge.ingest.pfa import (
    ACCOUNT_KIND_ALDERSOPSPARING,
    ACCOUNT_KIND_LIVRENTE,
    ACCOUNT_KIND_RATEPENSION,
    PROVIDER,
    TXN_KIND_CONTRIBUTION,
    parse_holdings_rows,
    parse_pensionsoversigt,
    parse_scheme_rows,
    synthesize_external_id,
)
from penge.ingest.pfa.parser import (
    _classify_contribution_source,
    _parse_dk_date,
    _parse_dk_number,
    _parse_dk_percent,
    _parse_metadata,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TEXT_FIXTURE = FIXTURES / "sample_pensionsoversigt.pdf"
SCANNED_FIXTURE = FIXTURES / "sample_pensionsoversigt_scanned.pdf"


# --- pure helpers ---------------------------------------------------------


class TestSynthesizeExternalId:
    def test_deterministic(self) -> None:
        a = synthesize_external_id(
            policy_number="12-345-678",
            scheme_kind=ACCOUNT_KIND_ALDERSOPSPARING,
            sub_policy_id="1",
            txn_kind=TXN_KIND_CONTRIBUTION,
            period_to=date(2025, 12, 31),
            detail="employer",
        )
        b = synthesize_external_id(
            policy_number="12-345-678",
            scheme_kind=ACCOUNT_KIND_ALDERSOPSPARING,
            sub_policy_id="1",
            txn_kind=TXN_KIND_CONTRIBUTION,
            period_to=date(2025, 12, 31),
            detail="employer",
        )
        assert a == b

    def test_namespaced(self) -> None:
        eid = synthesize_external_id(
            policy_number="12-345-678",
            scheme_kind=ACCOUNT_KIND_ALDERSOPSPARING,
            sub_policy_id="1",
            txn_kind=TXN_KIND_CONTRIBUTION,
            period_to=date(2025, 12, 31),
            detail="employer",
        )
        assert eid.startswith("pfa:")

    def test_distinct_for_distinct_inputs(self) -> None:
        a = synthesize_external_id(
            policy_number="12-345-678",
            scheme_kind=ACCOUNT_KIND_ALDERSOPSPARING,
            sub_policy_id="1",
            txn_kind=TXN_KIND_CONTRIBUTION,
            period_to=date(2025, 12, 31),
            detail="employer",
        )
        b = synthesize_external_id(
            policy_number="12-345-678",
            scheme_kind=ACCOUNT_KIND_ALDERSOPSPARING,
            sub_policy_id="1",
            txn_kind=TXN_KIND_CONTRIBUTION,
            period_to=date(2025, 12, 31),
            detail="employee",
        )
        assert a != b


class TestParseDkNumber:
    @pytest.mark.parametrize(  # type: ignore[untyped-decorator]  # pytest decorator is untyped under strict mypy
        "raw,expected",
        [
            ("1.234,56", Decimal("1234.56")),
            ("50.000,00", Decimal("50000.00")),
            ("0,00", Decimal("0.00")),
            ("-1.234,56", Decimal("-1234.56")),
            ("(1.234,56)", Decimal("-1234.56")),
            ("1.234,56 kr", Decimal("1234.56")),
            ("1.234,56 DKK", Decimal("1234.56")),
        ],
    )
    def test_locale_variants(self, raw: str, expected: Decimal) -> None:
        assert _parse_dk_number(raw) == expected

    @pytest.mark.parametrize("raw", ["", None, "abc", "—", "n/a"])  # type: ignore[untyped-decorator]  # pytest decorator is untyped under strict mypy
    def test_unparseable(self, raw: str | None) -> None:
        assert _parse_dk_number(raw) is None


class TestParseDkDate:
    def test_dot_format(self) -> None:
        assert _parse_dk_date("31.12.2025") == date(2025, 12, 31)

    def test_unparseable(self) -> None:
        assert _parse_dk_date("not a date") is None
        assert _parse_dk_date(None) is None


class TestParseDkPercent:
    def test_percent_with_unit(self) -> None:
        assert _parse_dk_percent("60,00 %") == Decimal("60.00")

    def test_percent_without_unit(self) -> None:
        assert _parse_dk_percent("60,00") == Decimal("60.00")

    def test_missing(self) -> None:
        assert _parse_dk_percent(None) is None


class TestClassifyContributionSource:
    @pytest.mark.parametrize(  # type: ignore[untyped-decorator]  # pytest decorator is untyped under strict mypy
        "label,expected",
        [
            ("indbetaling - arbejdsgiver", "employer"),
            ("indbetaling firma", "employer"),
            ("indbetaling - privat", "employee"),
            ("egen indbetaling", "employee"),
        ],
    )
    def test_labels(self, label: str, expected: str) -> None:
        assert _classify_contribution_source(label) == expected


class TestParseHoldingsRows:
    def test_basic(self) -> None:
        rows = [
            ["PFA Plus AA", "60,00 %", "120,5", "36.298,50"],
            ["PFA Globale Aktier", "30,00 %", "60,2", "18.149,25"],
            ["I alt", "100,00 %", "", "60.497,50"],
        ]
        out = parse_holdings_rows(rows)
        assert len(out) == 2
        assert out[0].fund_name == "PFA Plus AA"
        assert out[0].allocation_pct == Decimal("60.00")
        assert out[0].quantity == Decimal("120.5")
        assert out[0].market_value_dkk == Decimal("36298.50")

    def test_skips_short_or_empty_rows(self) -> None:
        out = parse_holdings_rows([["PFA Plus AA"], ["", ""], []])
        assert out == ()


class TestParseSchemeRows:
    def test_full_summary(self) -> None:
        rows = [
            ["Aldersopsparing", ""],
            ["Primo", "50.000,00"],
            ["Indbetaling - Arbejdsgiver", "0,00"],
            ["Indbetaling - Privat", "8.500,00"],
            ["Afkast", "2.500,00"],
            ["Omkostninger", "120,00"],
            ["PAL-skat", "382,50"],
            ["Ultimo", "60.497,50"],
        ]
        scheme = parse_scheme_rows(rows, sub_policy_id="1")
        assert scheme is not None
        assert scheme.scheme_kind == ACCOUNT_KIND_ALDERSOPSPARING
        assert scheme.opening_balance_dkk == Decimal("50000.00")
        assert scheme.closing_balance_dkk == Decimal("60497.50")
        assert scheme.return_dkk == Decimal("2500.00")
        assert scheme.fees_dkk == Decimal("120.00")
        assert scheme.pal_skat_dkk == Decimal("382.50")
        assert len(scheme.contributions) == 2
        assert {c.source for c in scheme.contributions} == {"employer", "employee"}

    def test_unrecognised_header_returns_none(self) -> None:
        assert parse_scheme_rows([["Mystery scheme", ""]], sub_policy_id="1") is None


class TestParseMetadata:
    def test_extracts_policy_and_period(self) -> None:
        text = (
            "PFA Pensionsoversigt\n"
            "Policenr.: 12-345-678\n"
            "Opgjort pr. 31.12.2025\n"
            "Optjeningsperiode: 01.01.2025 - 31.12.2025\n"
        )
        policy, as_of, period_from, period_to = _parse_metadata(text)
        assert policy == "12-345-678"
        assert as_of == date(2025, 12, 31)
        assert period_from == date(2025, 1, 1)
        assert period_to == date(2025, 12, 31)


# --- end-to-end -----------------------------------------------------------


@pytest.mark.skipif(
    not TEXT_FIXTURE.exists(),
    reason=(
        "Run `uv run --group parsers --group ocr python tools/generate_pfa_fixture.py`"
        " to produce the fixture."
    ),
)
class TestParsePensionsoversigt:
    def test_text_path(self) -> None:
        result = parse_pensionsoversigt(TEXT_FIXTURE, allow_ocr=False)
        assert result.policy_number == "12-345-678"
        assert result.as_of == date(2025, 12, 31)
        assert result.period_to == date(2025, 12, 31)
        assert result.extracted_via == "pdfplumber"
        kinds = {s.scheme_kind for s in result.schemes}
        assert kinds == {
            ACCOUNT_KIND_ALDERSOPSPARING,
            ACCOUNT_KIND_RATEPENSION,
            ACCOUNT_KIND_LIVRENTE,
        }

        aldersopsparing = next(
            s for s in result.schemes if s.scheme_kind == ACCOUNT_KIND_ALDERSOPSPARING
        )
        assert aldersopsparing.opening_balance_dkk == Decimal("50000.00")
        assert aldersopsparing.closing_balance_dkk == Decimal("60497.50")
        assert len(aldersopsparing.holdings) == 3

        # Reconciliation: opening + contribs + return - fees - pal_skat
        # ≈ closing (within 0.01 DKK rounding).
        for s in result.schemes:
            implied = (
                s.opening_balance_dkk
                + sum((c.amount_dkk for c in s.contributions), Decimal("0"))
                + s.return_dkk
                - s.fees_dkk
                - s.pal_skat_dkk
            )
            diff = abs(implied - s.closing_balance_dkk)
            assert diff <= Decimal("0.01"), f"reconciliation failed for {s.scheme_kind}: {diff}"

    def test_provider_constant(self) -> None:
        # Sanity-check that the public constant the loader relies on is
        # the lowercase short-name documented in the connector docs.
        assert PROVIDER == "pfa"


# --- OCR fallback ---------------------------------------------------------


# --- OCR fallback ---------------------------------------------------------


def _canned_tsv() -> dict[str, list[object]]:
    """A tiny Tesseract-style TSV for the Aldersopsparing summary.

    Two-column layout: label at x=100, amount at x=400 (gap >
    ``_OCR_CELL_GAP_PX``=80 → split into two cells per line). The
    leading rows contain the statement metadata so the parser can
    rebuild the page text directly from this TSV (single OCR pass).
    """

    # Block 1 holds the metadata header; block 2 holds the
    # financial-summary table. ``_ocr_words_to_tables`` splits on
    # ``block_num`` so the scheme detector sees the summary table
    # with "Aldersopsparing" as its first row.
    blocks: list[tuple[int, list[tuple[str, str]]]] = [
        (
            1,
            [
                ("PFA Pensionsoversigt", ""),
                ("Policenr.: 12-345-678", ""),
                ("Opgjort pr. 31.12.2025", ""),
                ("Optjeningsperiode: 01.01.2025 - 31.12.2025", ""),
            ],
        ),
        (
            2,
            [
                ("Aldersopsparing", ""),
                ("Primo", "50.000,00"),
                ("Indbetaling - Arbejdsgiver", "0,00"),
                ("Indbetaling - Privat", "8.500,00"),
                ("Afkast", "2.500,00"),
                ("Omkostninger", "120,00"),
                ("PAL-skat", "382,50"),
                ("Ultimo", "60.497,50"),
            ],
        ),
    ]
    text: list[object] = []
    block_num: list[object] = []
    par_num: list[object] = []
    line_num: list[object] = []
    left: list[object] = []
    for block, block_rows in blocks:
        for li, (label, amount) in enumerate(block_rows, start=1):
            for word in label.split():
                text.append(word)
                block_num.append(block)
                par_num.append(1)
                line_num.append(li)
                left.append(100)
            if amount:
                text.append(amount)
                block_num.append(block)
                par_num.append(1)
                line_num.append(li)
                left.append(400)
    return {
        "text": text,
        "block_num": block_num,
        "par_num": par_num,
        "line_num": line_num,
        "left": left,
    }


@pytest.mark.skipif(  # type: ignore[untyped-decorator]  # pytest decorator is untyped under strict mypy
    not SCANNED_FIXTURE.exists(),
    reason=(
        "Run `uv run --group parsers --group ocr python tools/generate_pfa_fixture.py`"
        " to produce the OCR fixture."
    ),
)
def test_ocr_fallback_path() -> None:
    """Force the OCR path and assert the parser still returns a scheme.

    pytesseract is mocked so the test does not depend on Danish/German
    Tesseract language packs being installed on the runner.
    """

    mocked_pytesseract = mock.MagicMock()
    mocked_pytesseract.image_to_data.return_value = _canned_tsv()

    class _Output:
        DICT = "dict"

    mocked_pytesseract.Output = _Output

    with mock.patch.dict(
        "sys.modules",
        {"pytesseract": mocked_pytesseract},
    ):
        # Pass a path that triggers OCR by reading the actual scanned
        # fixture (no embedded text → fallback path).
        result = parse_pensionsoversigt(SCANNED_FIXTURE, allow_ocr=True)

    assert result.extracted_via == "ocr"
    assert result.policy_number == "12-345-678"
    assert result.as_of == date(2025, 12, 31)
    assert any(s.scheme_kind == ACCOUNT_KIND_ALDERSOPSPARING for s in result.schemes)
