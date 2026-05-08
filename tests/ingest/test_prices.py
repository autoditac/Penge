"""Unit tests for the instrument price loader.

Network (yfinance) and DB (Postgres) are out of scope here — the
``run()`` happy path is exercised by an integration job in CI when
the loader graduates beyond pure-function coverage.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from penge.ingest.prices import (
    DISCREPANCY_THRESHOLD,
    MIC_TO_YAHOO_SUFFIX,
    Instrument,
    ParsedPrice,
    cross_check,
    resolve_yahoo_symbol,
)

# --------------------------------------------------------------------------- #
# resolve_yahoo_symbol
# --------------------------------------------------------------------------- #


def test_resolve_returns_none_when_no_ticker() -> None:
    assert resolve_yahoo_symbol(ticker=None, mic="XCSE") is None
    assert resolve_yahoo_symbol(ticker=None, mic=None, isin="DK0010274414") is None


def test_resolve_passes_through_already_suffixed_ticker() -> None:
    # If the ticker already has a venue dot, do not append a second.
    assert resolve_yahoo_symbol(ticker="NOVO-B.CO", mic="XCSE") == "NOVO-B.CO"
    assert resolve_yahoo_symbol(ticker="VWS.CO", mic=None) == "VWS.CO"


def test_resolve_appends_suffix_for_known_mic() -> None:
    assert resolve_yahoo_symbol(ticker="NOVO-B", mic="XCSE") == "NOVO-B.CO"
    assert resolve_yahoo_symbol(ticker="VOW3", mic="XETR") == "VOW3.DE"
    assert resolve_yahoo_symbol(ticker="HSBA", mic="XLON") == "HSBA.L"


def test_resolve_uses_no_suffix_for_us_mics() -> None:
    assert resolve_yahoo_symbol(ticker="AAPL", mic="XNAS") == "AAPL"
    assert resolve_yahoo_symbol(ticker="VTI", mic="ARCX") == "VTI"


def test_resolve_falls_back_to_bare_ticker_for_unknown_mic() -> None:
    # An unknown MIC should not corrupt the ticker.
    assert resolve_yahoo_symbol(ticker="AAPL", mic="ZZZZ") == "AAPL"


def test_resolve_strips_whitespace_on_ticker() -> None:
    assert resolve_yahoo_symbol(ticker="  AAPL  ", mic="XNAS") == "AAPL"


def test_resolve_returns_none_for_whitespace_only_ticker() -> None:
    # After ``.strip()`` the ticker is empty; we must not return a
    # bare suffix like ``.CO`` or an empty string.
    assert resolve_yahoo_symbol(ticker="   ", mic="XCSE") is None
    assert resolve_yahoo_symbol(ticker="\t\n", mic="XNAS") is None


def test_mic_table_only_contains_uppercase_mics() -> None:
    # Defensive: callers feed us instrument.mic verbatim, which is
    # CHAR(4) uppercase per the schema.
    for mic in MIC_TO_YAHOO_SUFFIX:
        assert mic == mic.upper()
        assert len(mic) == 4


# --------------------------------------------------------------------------- #
# cross_check
# --------------------------------------------------------------------------- #


def test_cross_check_zero_discrepancy() -> None:
    assert cross_check(Decimal("100.00"), Decimal("100.00")) == Decimal("0")


def test_cross_check_within_threshold() -> None:
    # 0.5 % difference must remain below the 1 % default threshold.
    rel = cross_check(Decimal("100.50"), Decimal("100.00"))
    assert rel == Decimal("0.005")
    assert rel <= DISCREPANCY_THRESHOLD


def test_cross_check_above_threshold() -> None:
    # 2 % difference must exceed the default threshold.
    rel = cross_check(Decimal("102.00"), Decimal("100.00"))
    assert rel == Decimal("0.02")
    assert rel > DISCREPANCY_THRESHOLD


def test_cross_check_is_symmetric_in_magnitude() -> None:
    # The function returns ``abs`` of the difference so direction
    # (yfinance > nordnet vs <) yields the same magnitude.
    rel_up = cross_check(Decimal("105"), Decimal("100"))
    rel_dn = cross_check(Decimal("95"), Decimal("100"))
    assert rel_up == Decimal("0.05")
    assert rel_dn == Decimal("0.05")


def test_cross_check_handles_negative_reference_via_abs() -> None:
    # Reference prices should never be negative in practice, but the
    # function should still produce a positive (though large) rel
    # value if a sign got flipped upstream — never a negative number.
    rel = cross_check(Decimal("90"), Decimal("-100"))
    assert rel == Decimal("1.9")
    assert rel >= 0


def test_cross_check_rejects_zero_reference() -> None:
    with pytest.raises(ValueError, match="non-zero"):
        cross_check(Decimal("1"), Decimal("0"))


# --------------------------------------------------------------------------- #
# Record types
# --------------------------------------------------------------------------- #


def test_parsed_price_is_immutable() -> None:
    p = ParsedPrice(
        instrument_id=uuid4(),
        as_of=date(2026, 5, 6),
        close=Decimal("123.45"),
        currency="DKK",
        source="yfinance",
    )

    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        # Intentional mutation of a frozen dataclass to assert immutability.
        p.close = Decimal("0")  # type: ignore[misc]


def test_instrument_record_round_trip() -> None:
    iid = uuid4()
    inst = Instrument(
        instrument_id=iid,
        name="Novo Nordisk B",
        kind="equity",
        currency="DKK",
        isin="DK0060534915",
        ticker="NOVO-B",
        mic="XCSE",
    )
    assert inst.instrument_id == iid
    # Resolve through the pure helper end-to-end.
    assert resolve_yahoo_symbol(ticker=inst.ticker, mic=inst.mic, isin=inst.isin) == "NOVO-B.CO"
