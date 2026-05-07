"""ECB FX loader — fetch, parse, upsert.

The feed has two shapes that differ only in nesting depth:

- Daily / 90-day: single ``<Cube time="YYYY-MM-DD">`` containing per-currency
  ``<Cube currency="USD" rate="1.0934"/>`` rows.
- Historical: a sequence of dated ``<Cube time="...">`` blocks, each
  containing the per-currency rows for that day.

We treat both uniformly: walk every ``Cube[time]`` and emit a ParsedRate for
each child currency row.
"""

from __future__ import annotations

import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

# --------------------------------------------------------------------------- #
# Feed catalogue
# --------------------------------------------------------------------------- #


class Feed(str, Enum):
    """The three ECB ``eurofxref`` feeds we consume."""

    DAILY = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
    LAST_90D = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
    HISTORICAL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ParsedRate:
    """One (date, base, quote, rate) tuple ready for upsert."""

    as_of: date
    base_ccy: str
    quote_ccy: str
    rate: Decimal
    source: str


# ECB XML uses the gesmes envelope namespace; element local-names are
# ``Cube`` regardless of nesting. Match by suffix to stay namespace-agnostic.
_CUBE_TAG_SUFFIX = "}Cube"


def parse(xml_bytes: bytes, *, source: str = "ECB") -> Iterator[ParsedRate]:
    """Parse ECB feed XML bytes into ``ParsedRate`` records.

    Yields one record per (date, currency) pair. EUR is always the base.
    Skips the EUR self-row if present (rate = 1).
    """
    root = ET.fromstring(xml_bytes)  # noqa: S314 — trusted ECB XML
    for dated in _iter_dated_cubes(root):
        as_of_str = dated.attrib.get("time")
        if not as_of_str:
            continue
        as_of = date.fromisoformat(as_of_str)
        for row in dated:
            if not row.tag.endswith(_CUBE_TAG_SUFFIX):
                continue
            ccy = row.attrib.get("currency")
            rate_str = row.attrib.get("rate")
            if not ccy or not rate_str:
                continue
            if ccy == "EUR":
                continue
            yield ParsedRate(
                as_of=as_of,
                base_ccy="EUR",
                quote_ccy=ccy,
                rate=Decimal(rate_str),
                source=source,
            )


def _iter_dated_cubes(root: ET.Element) -> Iterator[ET.Element]:
    """Yield every ``Cube`` element that carries a ``time`` attribute."""
    for el in root.iter():
        if el.tag.endswith(_CUBE_TAG_SUFFIX) and "time" in el.attrib:
            yield el


# --------------------------------------------------------------------------- #
# Network
# --------------------------------------------------------------------------- #

_USER_AGENT = "penge-ecb-fx-loader/0.0 (+https://github.com/autoditac/Penge)"


def fetch(feed: Feed, *, timeout: float = 30.0) -> bytes:
    """Download a feed; return raw XML bytes.

    Raises ``urllib.error.URLError`` on transport failures.
    """
    req = urllib.request.Request(feed.value, headers={"User-Agent": _USER_AGENT})  # noqa: S310 — fixed https URL
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed https URL
        data: bytes = resp.read()
    return data


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #


def upsert(engine: Engine, rates: Iterable[ParsedRate]) -> int:
    """Write ``rates`` to ``fx_rate``; return the number of rows written.

    Idempotent: ``ON CONFLICT (as_of, base_ccy, quote_ccy) DO UPDATE`` so a
    re-run with the same input is a no-op (apart from refreshing ``rate``
    and ``source`` if upstream restated them).
    """
    from sqlalchemy import MetaData, Table
    from sqlalchemy.dialects.postgresql import insert

    payload = [
        {
            "as_of": r.as_of,
            "base_ccy": r.base_ccy,
            "quote_ccy": r.quote_ccy,
            "rate": r.rate,
            "source": r.source,
        }
        for r in rates
    ]
    if not payload:
        return 0

    meta = MetaData()
    fx_rate = Table("fx_rate", meta, autoload_with=engine)
    stmt = insert(fx_rate).values(payload)
    stmt = stmt.on_conflict_do_update(
        constraint="ux_fx_rate__as_of_base_quote",
        set_={"rate": stmt.excluded.rate, "source": stmt.excluded.source},
    )
    with engine.begin() as conn:
        conn.execute(stmt)
    return len(payload)


# --------------------------------------------------------------------------- #
# Convenience
# --------------------------------------------------------------------------- #


def run(feed: Feed, engine: Engine) -> int:
    """Fetch + parse + upsert. Returns rows written."""
    xml_bytes = fetch(feed)
    rates = list(parse(xml_bytes))
    return upsert(engine, rates)
