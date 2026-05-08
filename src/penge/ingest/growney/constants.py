"""Vocabulary and shared regexes for the Growney / Sutor Bank ingest.

These string constants are the only literals other modules
(loader, dbt staging, marts) should match against. Do not
introduce a new transaction-kind value without updating the
canonical vocabulary in ADR-0008.
"""

from __future__ import annotations

import re
from typing import Final

# --- provider --------------------------------------------------------------

PROVIDER: Final = "growney"
"""account.provider value for every account ingested via Sutor PDFs."""

# --- account.kind ----------------------------------------------------------

ACCOUNT_KIND_AKTIEDEPOT: Final = "aktiedepot"
"""German Wertpapierdepot held at Sutor; taxable, Vorabpauschale applies.

We re-use the DK ``aktiedepot`` literal rather than introducing a
new kind because, semantically, both are "taxable securities depot".
The DE-specific tax overlay (Vorabpauschale, Teilfreistellung) is
applied downstream by the DE tax module, not by this connector.
"""

# --- transaction.kind ------------------------------------------------------

TXN_KIND_BUY: Final = "buy"
TXN_KIND_SELL: Final = "sell"
TXN_KIND_DEPOSIT: Final = "deposit"
TXN_KIND_WITHDRAWAL: Final = "withdrawal"
TXN_KIND_DIVIDEND: Final = "dividend"
TXN_KIND_FEE: Final = "fee"

# --- mapping: Sutor "Transaktion" column → canonical kind ------------------

# Sutor's spelling. The parser is locale-pinned to German.
SUTOR_TXN_TYPE_MAP: Final[dict[str, str]] = {
    "Einzahlung": TXN_KIND_DEPOSIT,
    "Auszahlung": TXN_KIND_WITHDRAWAL,
    "Kauf": TXN_KIND_BUY,
    "Verkauf": TXN_KIND_SELL,
    "Ausschüttung": TXN_KIND_DIVIDEND,
    "Gebühr": TXN_KIND_FEE,
}

# --- table headers (Sutor Depotauszug) -------------------------------------

# Holdings table — order matters because we parse positionally.
HOLDINGS_HEADERS: Final = (
    "Investment",
    "ISIN",
    "Lagerstelle",
    "Verwahrart",
    "Anlagequote",
    "Bestand",
    "Einheit",
    "Kurs",
    "Währung",
    "Kurswert",
)
HOLDINGS_COLS_REQUIRED: Final = len(HOLDINGS_HEADERS)

# Transactions table — Sutor splits some labels across two lines in
# the PDF; we match only the leading token to find the header row.
TRANSACTIONS_HEADER_FIRST: Final = "Buchungs-"
TRANSACTIONS_COLS_REQUIRED: Final = 14
"""Buchungsdatum, Wertstellung, Transaktion+Handelsplatz, Umsatz/ISIN+text,
Anteile/Gramm, Kurs/Preis, W-Kurs, Währung, Brutto, Netto, Kosten,
KESt+SolZ, KiSt — plus a synthetic 14th slot for split text rows."""

# --- regexes ---------------------------------------------------------------

# "Aufstellung über Kundenfinanzinstrumente per 31.03.2026"
AS_OF_RE: Final = re.compile(
    r"Aufstellung\s+über\s+Kundenfinanzinstrumente\s+per\s+"
    r"(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{4})"
)

# Depot header line, e.g. ' "growgreen100" Nr. 3361866701 / IBAN: DE41 ... '
# Strategy is quoted; depot number is a 10-digit run.
DEPOT_HEADER_RE: Final = re.compile(
    r'"(?P<strategy>[^"]+)"\s+Nr\.\s+(?P<depot>\d{10,})'
    r"\s*/\s*IBAN:\s*(?P<iban>[A-Z]{2}[A-Z0-9 ]+)"
)

# Umsatz period: "Umsätze vom 01.01.2026 bis 31.03.2026 in EUR"
PERIOD_RE: Final = re.compile(
    r"Umsätze\s+vom\s+"
    r"(?P<from_d>\d{1,2})\.(?P<from_m>\d{1,2})\.(?P<from_y>\d{4})"
    r"\s+bis\s+"
    r"(?P<to_d>\d{1,2})\.(?P<to_m>\d{1,2})\.(?P<to_y>\d{4})"
    r"\s+in\s+(?P<currency>[A-Z]{3})"
)

# ISIN — 12 alphanumeric characters.
ISIN_RE: Final = re.compile(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b")

# German number, e.g. "1.609,38" or "0,6186" or "-2,02".
DE_NUMBER_RE: Final = re.compile(r"^-?\d{1,3}(?:\.\d{3})*(?:,\d+)?$|^-?\d+(?:,\d+)?$")

# US$ unicode marker on Sutor PDFs sometimes drops the '*' footnote.
USD_MARKERS: Final = ("US$", "USD")

# Fixture for "Geldsaldo" line.
CASH_BALANCE_LABEL: Final = "Geldsaldo"
KURSWERT_TOTAL_LABEL: Final = "Kurswert Gesamt"

# External-id namespace for synthesized transaction ids.
EXTERNAL_ID_PREFIX: Final = "growney:"
EXTERNAL_ID_HASH_LEN: Final = 16
"""sha256 hex digest length used for transaction external_id."""

__all__ = [
    "ACCOUNT_KIND_AKTIEDEPOT",
    "AS_OF_RE",
    "CASH_BALANCE_LABEL",
    "DEPOT_HEADER_RE",
    "DE_NUMBER_RE",
    "EXTERNAL_ID_HASH_LEN",
    "EXTERNAL_ID_PREFIX",
    "HOLDINGS_COLS_REQUIRED",
    "HOLDINGS_HEADERS",
    "ISIN_RE",
    "KURSWERT_TOTAL_LABEL",
    "PERIOD_RE",
    "PROVIDER",
    "SUTOR_TXN_TYPE_MAP",
    "TRANSACTIONS_COLS_REQUIRED",
    "TRANSACTIONS_HEADER_FIRST",
    "TXN_KIND_BUY",
    "TXN_KIND_DEPOSIT",
    "TXN_KIND_DIVIDEND",
    "TXN_KIND_FEE",
    "TXN_KIND_SELL",
    "TXN_KIND_WITHDRAWAL",
    "USD_MARKERS",
]
