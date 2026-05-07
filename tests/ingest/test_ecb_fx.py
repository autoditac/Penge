"""Unit tests for the ECB FX parser.

Network and DB are out of scope here — those paths are exercised by the
integration job in CI (``ecb-fx`` workflow, manual dispatch).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from penge.ingest.ecb_fx import ParsedRate, parse

# A minimal but realistic daily-feed sample. Real ECB XML uses two
# namespaces (gesmes envelope + eurofxref); the parser keys on element
# local-names so it stays robust to that.
DAILY_SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <gesmes:Sender>
    <gesmes:name>European Central Bank</gesmes:name>
  </gesmes:Sender>
  <Cube>
    <Cube time="2026-05-06">
      <Cube currency="USD" rate="1.0934"/>
      <Cube currency="DKK" rate="7.4612"/>
      <Cube currency="GBP" rate="0.8523"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""

# The historical feed nests one dated Cube per business day.
HIST_SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-05-06">
      <Cube currency="USD" rate="1.0934"/>
      <Cube currency="DKK" rate="7.4612"/>
    </Cube>
    <Cube time="2026-05-05">
      <Cube currency="USD" rate="1.0901"/>
      <Cube currency="DKK" rate="7.4608"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""


def test_parse_daily_yields_one_row_per_currency() -> None:
    rows = list(parse(DAILY_SAMPLE))

    assert len(rows) == 3
    assert all(r.as_of == date(2026, 5, 6) for r in rows)
    assert {r.quote_ccy for r in rows} == {"USD", "DKK", "GBP"}
    assert all(r.base_ccy == "EUR" for r in rows)


def test_parse_historical_yields_rows_per_day() -> None:
    rows = list(parse(HIST_SAMPLE))

    assert len(rows) == 4
    by_day = {r.as_of for r in rows}
    assert by_day == {date(2026, 5, 6), date(2026, 5, 5)}


def test_parse_preserves_decimal_precision() -> None:
    [usd] = [r for r in parse(DAILY_SAMPLE) if r.quote_ccy == "USD"]

    # No float round-trip; the Decimal must equal the literal exactly.
    assert usd.rate == Decimal("1.0934")
    assert isinstance(usd.rate, Decimal)


def test_parse_skips_eur_self_row() -> None:
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-05-06">
      <Cube currency="EUR" rate="1.0000"/>
      <Cube currency="USD" rate="1.0934"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""
    rows = list(parse(xml))

    assert [r.quote_ccy for r in rows] == ["USD"]


def test_parsed_rate_is_immutable() -> None:
    r = ParsedRate(
        as_of=date(2026, 5, 6),
        base_ccy="EUR",
        quote_ccy="USD",
        rate=Decimal("1.0934"),
        source="ECB",
    )

    import dataclasses

    try:
        # frozen dataclasses raise FrozenInstanceError on assignment
        r.rate = Decimal("2")  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("expected FrozenInstanceError")


def test_parse_tags_source() -> None:
    [r, *_] = parse(DAILY_SAMPLE, source="ECB-test")

    assert r.source == "ECB-test"
