"""Pure parsing logic for the Sutor Bank Depotauszug PDF.

This module is split into:

- *pure* helpers (``_parse_de_number``, ``_parse_de_date``,
  ``synthesize_external_id``, ``parse_holdings_rows``,
  ``parse_transactions_rows``) that operate on already-extracted
  table cells; these are the unit-test surface;
- ``parse_depotauszug`` / ``parse_pdf`` which open a PDF with
  pdfplumber and feed the extracted tables and full-page text
  into the pure helpers.

Sutor formats numbers in DE locale (``1.234,56``). All money
columns in the Umsätze table are denominated in EUR; the unit
price column may be USD with a separate W-Kurs column carrying
the EUR/foreign FX rate. ``Betrag (netto)`` is signed (negative
for outflows like ``Kauf`` and ``Gebühr``).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING

from penge.ingest.growney.constants import (
    AS_OF_RE,
    DEPOT_HEADER_RE,
    EXTERNAL_ID_HASH_LEN,
    EXTERNAL_ID_PREFIX,
    HOLDINGS_HEADERS,
    ISIN_RE,
    PERIOD_RE,
    SUTOR_TXN_TYPE_MAP,
    TXN_KIND_BUY,
    TXN_KIND_DEPOSIT,
    TXN_KIND_DIVIDEND,
    TXN_KIND_FEE,
    TXN_KIND_SELL,
    TXN_KIND_WITHDRAWAL,
    USD_MARKERS,
)
from penge.ingest.growney.models import (
    ParsedDepotauszug,
    ParsedHolding,
    ParsedTransaction,
)

if TYPE_CHECKING:
    pass


# --- public API ------------------------------------------------------------


def parse_depotauszug(pdf_path: str | Path) -> ParsedDepotauszug:
    """Open *pdf_path* with pdfplumber and return a fully parsed Depotauszug."""

    # Imported lazily so the module can be imported by users who only
    # need the pure parsing helpers (without installing pdfplumber).
    import pdfplumber

    pdf_path = Path(pdf_path)
    holdings_rows: list[list[str | None]] = []
    transactions_rows: list[list[str | None]] = []
    full_text_parts: list[str] = []
    cash_balance_eur: Decimal = Decimal("0")
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            full_text_parts.append(page_text)
            for raw_table in page.extract_tables() or []:
                rows = [[(c or "").strip() or None for c in row] for row in raw_table]
                if not rows:
                    continue
                header = " ".join((c or "") for c in rows[0])
                if "Investment" in header and "ISIN" in header:
                    holdings_rows.extend(rows[1:])
                elif "Buchungs" in header and "Wertstellung" in header:
                    transactions_rows.extend(_skip_transaction_header_rows(rows))
            cash_balance_eur = _extract_cash_balance(page_text) or cash_balance_eur
    full_text = "\n".join(full_text_parts)
    metadata = _parse_metadata(full_text)
    holdings = parse_holdings_rows(holdings_rows)
    transactions = parse_transactions_rows(transactions_rows)
    return ParsedDepotauszug(
        depot_number=metadata.depot_number,
        iban=metadata.iban,
        strategy=metadata.strategy,
        as_of=metadata.as_of,
        period_from=metadata.period_from,
        period_to=metadata.period_to,
        holdings=holdings,
        transactions=transactions,
        cash_balance_eur=cash_balance_eur,
    )


# Convenience alias matching the rest of the codebase's naming.
parse_pdf = parse_depotauszug


def synthesize_external_id(
    *,
    depot_number: str,
    bookkeeping_date: date,
    value_date: date,
    sutor_type: str,
    isin: str | None,
    quantity: Decimal | None,
    net_amount_eur: Decimal,
    description: str | None,
) -> str:
    """Stable hash-based external id for one Sutor transaction row.

    Sutor exports do not carry a transaction id. We hash a tuple
    of stable, human-meaningful fields (excluding any that the
    bank might re-format, such as the time-of-day suffix) so the
    same physical transaction always yields the same id across
    re-runs and across statement periods (some rows appear on the
    boundary statement of two quarters).
    """

    parts = (
        depot_number,
        bookkeeping_date.isoformat(),
        value_date.isoformat(),
        sutor_type,
        isin or "",
        f"{quantity:f}" if quantity is not None else "",
        f"{net_amount_eur:f}",
        (description or "").strip(),
    )
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"{EXTERNAL_ID_PREFIX}{digest[:EXTERNAL_ID_HASH_LEN]}"


# --- holdings --------------------------------------------------------------


def parse_holdings_rows(rows: Sequence[Sequence[str | None]]) -> tuple[ParsedHolding, ...]:
    """Convert the raw cells of the holdings table into typed records."""

    out: list[ParsedHolding] = []
    for row in rows:
        cells = [c for c in row if c is not None and c.strip()]
        if not cells:
            continue
        # Skip section labels Sutor injects, e.g. a single-cell row "Fonds"
        # or footnote rows like "* Währungskurs: 1,1498 US$".
        if len(cells) < len(HOLDINGS_HEADERS):
            continue
        if not _looks_like_isin(cells[1]):
            continue
        out.append(_row_to_holding(cells))
    return tuple(out)


def _row_to_holding(cells: Sequence[str]) -> ParsedHolding:
    name = cells[0]
    isin = cells[1].strip()
    lagerstelle = cells[2] or None
    verwahrart = cells[3] or None
    allocation_pct = _parse_de_percent(cells[4])
    quantity = _parse_de_number_required(cells[5], field="Bestand")
    unit = cells[6]
    price = _parse_de_number(cells[7])
    price_currency = _parse_currency_marker(cells[8])
    market_value_eur = _parse_de_number_with_currency(cells[9], expected_currency="EUR")
    return ParsedHolding(
        name=name,
        isin=isin,
        lagerstelle=lagerstelle,
        verwahrart=verwahrart,
        allocation_pct=allocation_pct,
        quantity=quantity,
        unit=unit,
        price=price,
        price_currency=price_currency,
        market_value_eur=market_value_eur,
    )


# --- transactions ----------------------------------------------------------


def _skip_transaction_header_rows(rows: list[list[str | None]]) -> list[list[str | None]]:
    """Drop the (possibly multi-line) header rows of the Umsätze table.

    Sutor stacks header words across two visual lines
    ("Buchungs- / datum"); the first row may also be the legend
    line. We skip leading rows whose first cell does not look
    like a German date.
    """

    for i, row in enumerate(rows):
        first = (row[0] or "").strip() if row else ""
        if _looks_like_de_date(first):
            return rows[i:]
    return []


def parse_transactions_rows(
    rows: Sequence[Sequence[str | None]],
) -> tuple[ParsedTransaction, ...]:
    """Convert the raw cells of the Umsätze table into typed records.

    The expected column order, from the Sutor 2026 layout:
    0: Buchungsdatum
    1: Wertstellung (may carry a "HH:MM" suffix on a second line)
    2: Transaktion (with Handelsplatz on the next line)
    3: Umsatz / Finanz-Instrument (with ISIN on the next line)
    4: Anteile / Gramm (with Kurs / Preis on the next line)
    5: W-Kurs (with Währung on the next line)
    6: Betrag (brutto), in EUR
    7: Betrag (netto), in EUR
    8: Kosten
    9: KESt + SolZ
    10: KiSt
    """

    out: list[ParsedTransaction] = []
    for row in rows:
        first = (row[0] or "").strip() if row else ""
        if not _looks_like_de_date(first):
            continue
        out.append(_row_to_transaction(row))
    return tuple(out)


def _row_to_transaction(row: Sequence[str | None]) -> ParsedTransaction:
    bookkeeping_date = _parse_de_date(_cell(row, 0) or "")
    value_cell = _cell(row, 1) or ""
    value_date = _parse_de_date(value_cell.split("\n")[0])
    txn_cell = _cell(row, 2) or ""
    sutor_type, venue = _split_two_lines(txn_cell)
    desc_cell = _cell(row, 3) or ""
    description, isin_from_desc = _split_description_and_isin(desc_cell)
    qty_cell = _cell(row, 4) or ""
    quantity, unit_price = _split_quantity_and_unit_price(qty_cell)
    fx_cell = _cell(row, 5) or ""
    fx_rate, unit_price_currency = _split_fx_and_currency(fx_cell)
    gross_amount_eur = _parse_de_number(_cell(row, 6))
    net_amount_eur = _parse_de_number_required(_cell(row, 7), field="Betrag (netto)")
    fees_eur = _parse_de_number(_cell(row, 8))
    capital_tax_eur = _parse_de_number(_cell(row, 9))
    church_tax_eur = _parse_de_number(_cell(row, 10))
    kind = _resolve_kind(sutor_type=sutor_type)
    return ParsedTransaction(
        bookkeeping_date=bookkeeping_date,
        value_date=value_date,
        kind=kind,
        sutor_type=sutor_type,
        venue=venue,
        description=description or None,
        isin=isin_from_desc,
        quantity=quantity,
        unit_price=unit_price,
        unit_price_currency=unit_price_currency,
        fx_rate=fx_rate,
        gross_amount_eur=gross_amount_eur,
        net_amount_eur=net_amount_eur,
        fees_eur=fees_eur,
        capital_tax_eur=capital_tax_eur,
        church_tax_eur=church_tax_eur,
    )


def _resolve_kind(*, sutor_type: str) -> str:
    direct = SUTOR_TXN_TYPE_MAP.get(sutor_type)
    if direct is not None:
        return direct
    raise ValueError(f"unknown Sutor Transaktion {sutor_type!r}")


# --- metadata --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Metadata:
    depot_number: str
    iban: str | None
    strategy: str | None
    as_of: date
    period_from: date | None
    period_to: date | None


def _parse_metadata(full_text: str) -> _Metadata:
    m = AS_OF_RE.search(full_text)
    if not m:
        raise ValueError("could not find 'Aufstellung über Kundenfinanzinstrumente per ...'")
    as_of = date(int(m["year"]), int(m["month"]), int(m["day"]))
    h = DEPOT_HEADER_RE.search(full_text)
    if h is None:
        raise ValueError("could not parse depot header (strategy / Nr / IBAN)")
    strategy = h["strategy"].strip()
    depot_number = h["depot"]
    iban = re.sub(r"\s+", "", h["iban"])
    p = PERIOD_RE.search(full_text)
    period_from: date | None = None
    period_to: date | None = None
    if p is not None:
        period_from = date(int(p["from_y"]), int(p["from_m"]), int(p["from_d"]))
        period_to = date(int(p["to_y"]), int(p["to_m"]), int(p["to_d"]))
    return _Metadata(
        depot_number=depot_number,
        iban=iban,
        strategy=strategy,
        as_of=as_of,
        period_from=period_from,
        period_to=period_to,
    )


def _extract_cash_balance(page_text: str) -> Decimal | None:
    # "Geldsaldo 0,00 EUR" or "Geldsaldo 12,34 EUR"
    m = re.search(r"Geldsaldo\s+(-?[\d.,]+)\s+EUR", page_text)
    if m is None:
        return None
    return _parse_de_number(m.group(1))


# --- low-level helpers -----------------------------------------------------


_DE_DATE_RE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}$")
_PCT_RE = re.compile(r"^(?P<num>-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|\-?\d+(?:,\d+)?)\s*%$")


def _looks_like_de_date(s: str) -> bool:
    return bool(_DE_DATE_RE.match(s.strip()))


def _looks_like_isin(s: str | None) -> bool:
    return bool(s and ISIN_RE.match(s.strip()))


def _cell(row: Sequence[str | None], i: int) -> str | None:
    if i >= len(row):
        return None
    return row[i]


def _parse_de_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%d.%m.%Y").date()


def _parse_de_number(s: str | None) -> Decimal | None:
    if s is None:
        return None
    raw = s.strip().replace("\u202f", "").replace("\xa0", " ").rstrip("EUR").strip()
    raw = raw.split()[0] if raw else ""
    if not raw or raw in {"-"}:
        return None
    cleaned = raw.replace(".", "").replace(",", ".") if "," in raw else raw
    try:
        return Decimal(cleaned)
    except InvalidOperation as e:
        raise ValueError(f"cannot parse decimal {s!r}") from e


def _parse_de_number_required(s: str | None, *, field: str) -> Decimal:
    val = _parse_de_number(s)
    if val is None:
        raise ValueError(f"missing required numeric field {field!r}: {s!r}")
    return val


def _parse_de_percent(s: str | None) -> Decimal | None:
    if s is None:
        return None
    m = _PCT_RE.match(s.strip())
    if m is None:
        return None
    return _parse_de_number(m.group("num"))


def _parse_currency_marker(s: str | None) -> str:
    if s is None:
        return "EUR"
    raw = s.strip().rstrip("*")
    if raw in USD_MARKERS:
        return "USD"
    return raw or "EUR"


def _parse_de_number_with_currency(s: str | None, *, expected_currency: str) -> Decimal:
    """Parse a cell shaped like ``77,66 EUR`` (single combined cell)."""

    if s is None:
        raise ValueError("expected number-with-currency, got None")
    parts = s.strip().split()
    if not parts:
        raise ValueError(f"empty number-with-currency cell {s!r}")
    if parts[-1] != expected_currency:
        raise ValueError(f"expected trailing {expected_currency!r}, got {parts[-1]!r} in {s!r}")
    val = _parse_de_number(parts[0])
    if val is None:
        raise ValueError(f"cannot parse leading number in {s!r}")
    return val


def _split_two_lines(s: str) -> tuple[str, str | None]:
    parts = [p.strip() for p in s.split("\n") if p.strip()]
    if not parts:
        return "", None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1]


def _split_description_and_isin(s: str) -> tuple[str, str | None]:
    parts = [p.strip() for p in s.split("\n") if p.strip()]
    if not parts:
        return "", None
    isin_match: str | None = None
    description_lines: list[str] = []
    for p in parts:
        m = ISIN_RE.search(p)
        if m and m.group(0).strip() == p.strip():
            isin_match = m.group(0)
        else:
            description_lines.append(p)
    return " ".join(description_lines).strip(), isin_match


def _split_quantity_and_unit_price(s: str) -> tuple[Decimal | None, Decimal | None]:
    """Cell shape: ``0,0148\\n136,0400 EUR`` or ``-`` or ``2,4378\\n11,9671``."""

    parts = [p.strip() for p in s.split("\n") if p.strip()]
    if not parts:
        return None, None
    quantity = _parse_de_number(parts[0]) if parts[0] != "-" else None
    unit_price = None
    if len(parts) > 1:
        unit_price = _parse_de_number(parts[1])
    return quantity, unit_price


def _split_fx_and_currency(s: str) -> tuple[Decimal | None, str | None]:
    """Cell shape: ``1,1721\\nUS$`` or just ``EUR`` or ``-``."""

    parts = [p.strip() for p in s.split("\n") if p.strip() and p.strip() != "-"]
    if not parts:
        return None, None
    fx: Decimal | None = None
    currency: str | None = None
    for p in parts:
        if p in USD_MARKERS or p == "EUR":
            currency = _parse_currency_marker(p)
        else:
            candidate = _parse_de_number(p)
            if candidate is not None:
                fx = candidate
    return fx, currency


__all__ = [
    "TXN_KIND_BUY",
    "TXN_KIND_DEPOSIT",
    "TXN_KIND_DIVIDEND",
    "TXN_KIND_FEE",
    "TXN_KIND_SELL",
    "TXN_KIND_WITHDRAWAL",
    "parse_depotauszug",
    "parse_holdings_rows",
    "parse_pdf",
    "parse_transactions_rows",
    "synthesize_external_id",
]
