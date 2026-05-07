"""Parsing logic for Nordnet DK CSV exports.

See `docs/connectors/nordnet.md` for the runbook and ADR-0008 for
the modelling decisions.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Iterator
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import IO

from penge.ingest.nordnet.constants import (
    NORDNET_BOM,
    NORDNET_CSV_DELIMITER,
    NORDNET_CSV_ENCODING,
    NORDNET_TXN_TYPE_MAP,
    TXN_KIND_DEPOSIT,
    TXN_KIND_INTERNAL_TRANSFER,
    TXN_KIND_WITHDRAWAL,
)
from penge.ingest.nordnet.models import (
    ParsedCashBalance,
    ParsedHolding,
    ParsedHoldingsFile,
    ParsedTransaction,
)

# --- header layouts (positional, 1-indexed in docstrings; 0-indexed in code) -

# Transaction CSV — 30 columns. The column name ``Valuta`` repeats
# five times (positions 13, 15, 17, 19, 28). We parse positionally,
# never by name dedup.
_TXN_COL_ID = 0
_TXN_COL_BOOKKEEPING = 1
_TXN_COL_TRADE = 2
_TXN_COL_VALUE = 3
_TXN_COL_DEPOT = 4
_TXN_COL_TYPE = 5
_TXN_COL_INSTRUMENT = 6
_TXN_COL_ISIN = 7
_TXN_COL_QUANTITY = 8
_TXN_COL_PRICE = 9
_TXN_COL_FEES = 11
_TXN_COL_AMOUNT_CCY = 12  # 13th column "Valuta"
_TXN_COL_AMOUNT = 13
_TXN_COL_SALDO = 20
_TXN_COL_FX = 21
_TXN_COL_TEXT = 22
_TXN_COLS_REQUIRED = 30

_TXN_HEADER_FIRST = "Id"

# Holdings CSV — 10 columns.
_HLD_COL_NAME = 0
_HLD_COL_CURRENCY = 1
_HLD_COL_QUANTITY = 2
_HLD_COL_AVG_COST = 3
_HLD_COL_LAST_PRICE = 5
_HLD_COL_VALUE_DKK = 7
_HLD_COL_RETURN_PCT = 8
_HLD_COL_RETURN_DKK = 9
_HLD_COLS_REQUIRED = 10

_HLD_HEADER_FIRST = "Navn"

# Filename like: "Depotoversigt for kontonummer 60109543, 7.5.2026.csv"
_HOLDINGS_FILENAME_RE = re.compile(
    r"^Depotoversigt for kontonummer\s+(?P<account>\d+),\s*"
    r"(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{4})\.csv$"
)

# Internal-transfer counter-account, e.g. "Internal from 60109543"
# or "Internal to 67130203".
_INTERNAL_COUNTER_RE = re.compile(
    r"\bInternal\s+(?:from|to)\s+(?P<account>\d+)\b",
    re.IGNORECASE,
)


class UnknownAccountError(KeyError):
    """Raised when a transaction references an account not in config."""


# --- public API -------------------------------------------------------------


def parse_transactions(source: str | Path | IO[str]) -> Iterator[ParsedTransaction]:
    """Yield :class:`ParsedTransaction` rows from a Nordnet transactions CSV.

    Accepts either a filesystem path (UTF-16LE BOM, tab-separated)
    or a pre-opened text stream (already decoded).
    """

    rows = _iter_csv_rows(source, expected_first_header=_TXN_HEADER_FIRST)
    header = next(rows, None)
    if header is None:
        return
    if len(header) < _TXN_COLS_REQUIRED:
        raise ValueError(
            f"unexpected transactions header: {len(header)} columns, "
            f"expected {_TXN_COLS_REQUIRED}"
        )

    for row in rows:
        # Pad short rows; Nordnet emits trailing-empty rows for some types.
        if len(row) < _TXN_COLS_REQUIRED:
            row = [*row, *([""] * (_TXN_COLS_REQUIRED - len(row)))]
        yield _row_to_transaction(row)


def parse_holdings(source: str | Path | IO[str]) -> tuple[ParsedHolding, ...]:
    """Parse the holdings rows from a Nordnet *Depotoversigt* CSV.

    Use :func:`parse_holdings_filename` separately to pull
    ``account_number`` and ``as_of`` from the filename, then wrap
    both with :class:`ParsedHoldingsFile`. (Or call
    :func:`parse_holdings_file` for the bundled convenience.)
    """

    rows = _iter_csv_rows(source, expected_first_header=_HLD_HEADER_FIRST)
    header = next(rows, None)
    if header is None:
        return ()
    if len(header) < _HLD_COLS_REQUIRED:
        raise ValueError(
            f"unexpected holdings header: {len(header)} columns, " f"expected {_HLD_COLS_REQUIRED}"
        )

    out: list[ParsedHolding] = []
    for row in rows:
        if not row or not row[_HLD_COL_NAME].strip():
            continue
        if len(row) < _HLD_COLS_REQUIRED:
            row = [*row, *([""] * (_HLD_COLS_REQUIRED - len(row)))]
        out.append(_row_to_holding(row))
    return tuple(out)


def parse_holdings_filename(filename: str | Path) -> tuple[str, date]:
    """Extract ``(account_number, as_of)`` from a holdings filename.

    Filenames look like ``Depotoversigt for kontonummer 60109543,
    7.5.2026.csv``. Raises :class:`ValueError` on a non-matching name.
    """

    name = Path(filename).name
    m = _HOLDINGS_FILENAME_RE.match(name)
    if m is None:
        raise ValueError(f"not a Nordnet holdings filename: {name!r}")
    account = m.group("account")
    as_of = date(int(m.group("year")), int(m.group("month")), int(m.group("day")))
    return account, as_of


def parse_holdings_file(path: str | Path) -> ParsedHoldingsFile:
    """Convenience: parse a holdings CSV and bundle filename metadata."""

    account, as_of = parse_holdings_filename(path)
    return ParsedHoldingsFile(
        account_number=account,
        as_of=as_of,
        holdings=parse_holdings(path),
    )


def instrument_map_from_transactions(
    txns: Iterable[ParsedTransaction],
) -> dict[str, str]:
    """Build a ``Navn -> ISIN`` map from a transaction stream.

    Holdings CSVs lack ISIN; transactions have both. The first
    non-empty (name, isin) pair wins; later conflicts are reported
    via :class:`ValueError` so a typo can't silently overwrite a
    real mapping.
    """

    out: dict[str, str] = {}
    for t in txns:
        if not t.instrument_name or not t.isin:
            continue
        existing = out.get(t.instrument_name)
        if existing is None:
            out[t.instrument_name] = t.isin
        elif existing != t.isin:
            raise ValueError(
                f"conflicting ISIN for {t.instrument_name!r}: " f"{existing!r} vs {t.isin!r}"
            )
    return out


def derive_cash_balances(
    txns: Iterable[ParsedTransaction],
) -> tuple[ParsedCashBalance, ...]:
    """Derive cash sub-balances per (account, currency).

    Picks the row with the latest ``value_date`` (or
    ``bookkeeping_date`` as fallback) per ``(account_number,
    amount_currency)`` and reports its ``saldo``. Rows without a
    ``saldo`` are ignored (some Nordnet types — notably internal
    transfers from the donor side — omit it).
    """

    latest: dict[tuple[str, str], ParsedTransaction] = {}
    for t in txns:
        if t.saldo is None:
            continue
        key = (t.account_number, t.amount_currency)
        prev = latest.get(key)
        if prev is None or _txn_sort_key(t) > _txn_sort_key(prev):
            latest[key] = t

    out: list[ParsedCashBalance] = []
    for (account, currency), t in latest.items():
        as_of = t.value_date or t.bookkeeping_date
        # mypy-narrow: saldo is non-None by construction above.
        assert t.saldo is not None
        out.append(
            ParsedCashBalance(
                account_number=account,
                currency=currency,
                saldo=t.saldo,
                as_of=as_of,
            )
        )
    out.sort(key=lambda c: (c.account_number, c.currency))
    return tuple(out)


# --- internals --------------------------------------------------------------


def _iter_csv_rows(
    source: str | Path | IO[str],
    *,
    expected_first_header: str,
) -> Iterator[list[str]]:
    """Yield rows from a Nordnet CSV, decoding UTF-16LE BOM if needed.

    ``source`` may be a path or an already-opened text stream. The
    BOM is stripped from the first cell of the first row. The
    function raises :class:`ValueError` if the first cell does not
    match ``expected_first_header`` after BOM stripping (catches
    locale/format mismatches early).
    """

    if isinstance(source, (str, Path)):
        # Nordnet writes UTF-16LE with a BOM. Python's "utf-16"
        # codec auto-detects it; we use the explicit name to avoid
        # any locale surprises and strip the BOM ourselves.
        f = open(source, encoding=NORDNET_CSV_ENCODING, newline="")  # noqa: SIM115
        try:
            yield from _read_rows(f, expected_first_header)
        finally:
            f.close()
    else:
        yield from _read_rows(source, expected_first_header)


def _read_rows(stream: IO[str], expected_first_header: str) -> Iterator[list[str]]:
    reader = csv.reader(stream, delimiter=NORDNET_CSV_DELIMITER)
    first = True
    for row in reader:
        if first:
            first = False
            if row and row[0].startswith(NORDNET_BOM):
                row[0] = row[0][len(NORDNET_BOM) :]
            if not row or row[0] != expected_first_header:
                got = row[0] if row else ""
                raise ValueError(
                    f"unexpected first column {got!r}; " f"expected {expected_first_header!r}"
                )
        yield row


def _row_to_transaction(row: list[str]) -> ParsedTransaction:
    nordnet_type = row[_TXN_COL_TYPE].strip()
    text = _opt_str(row[_TXN_COL_TEXT])
    counter_account = _extract_counter_account(text)
    canonical_kind = _resolve_canonical_kind(
        nordnet_type=nordnet_type,
        amount=_decimal_or_none(row[_TXN_COL_AMOUNT]),
        counter_account=counter_account,
    )
    amount = _decimal_or_none(row[_TXN_COL_AMOUNT])
    if amount is None:
        raise ValueError(f"transaction {row[_TXN_COL_ID]!r} has no Beløb amount")
    amount_currency = _resolve_amount_currency(row)
    return ParsedTransaction(
        nordnet_id=row[_TXN_COL_ID].strip(),
        bookkeeping_date=_date(row[_TXN_COL_BOOKKEEPING]),
        trade_date=_date_or_none(row[_TXN_COL_TRADE]),
        value_date=_date_or_none(row[_TXN_COL_VALUE]),
        account_number=row[_TXN_COL_DEPOT].strip(),
        nordnet_type=nordnet_type,
        canonical_kind=canonical_kind,
        instrument_name=_opt_str(row[_TXN_COL_INSTRUMENT]),
        isin=_opt_str(row[_TXN_COL_ISIN]),
        quantity=_decimal_or_none(row[_TXN_COL_QUANTITY]),
        price=_decimal_or_none(row[_TXN_COL_PRICE]),
        fees=_decimal_or_none(row[_TXN_COL_FEES]),
        amount=amount,
        amount_currency=amount_currency,
        saldo=_decimal_or_none(row[_TXN_COL_SALDO]),
        fx_rate=_decimal_or_none(row[_TXN_COL_FX]),
        text=text,
        counter_account=counter_account,
    )


def _row_to_holding(row: list[str]) -> ParsedHolding:
    qty = _decimal_or_none(row[_HLD_COL_QUANTITY])
    if qty is None:
        raise ValueError(f"holding row {row[_HLD_COL_NAME]!r} has no Antal")
    return ParsedHolding(
        name=row[_HLD_COL_NAME].strip(),
        currency=row[_HLD_COL_CURRENCY].strip(),
        quantity=qty,
        avg_cost=_decimal_or_none(row[_HLD_COL_AVG_COST]),
        last_price=_decimal_or_none(row[_HLD_COL_LAST_PRICE]),
        market_value_dkk=_decimal_or_none(row[_HLD_COL_VALUE_DKK]),
        return_pct=_decimal_or_none(row[_HLD_COL_RETURN_PCT]),
        return_dkk=_decimal_or_none(row[_HLD_COL_RETURN_DKK]),
    )


def _resolve_canonical_kind(
    *,
    nordnet_type: str,
    amount: Decimal | None,
    counter_account: str | None,
) -> str:
    """Map Nordnet's Transaktionstype to canonical kind.

    `INDSÆTTELSE`/`HÆVNING` become `internal_transfer` if the text
    mentions a counter-account; otherwise they are treated as
    external `deposit`/`withdrawal` based on the sign of `amount`.
    """

    direct = NORDNET_TXN_TYPE_MAP.get(nordnet_type)
    if direct is not None:
        return direct
    if nordnet_type in {"INDSÆTTELSE", "HÆVNING"}:
        if counter_account is not None:
            return TXN_KIND_INTERNAL_TRANSFER
        if amount is not None and amount < 0:
            return TXN_KIND_WITHDRAWAL
        return TXN_KIND_DEPOSIT
    raise ValueError(f"unknown Nordnet Transaktionstype {nordnet_type!r}")


def _resolve_amount_currency(row: list[str]) -> str:
    """Pick the currency of the Beløb column, falling back to DKK.

    Nordnet leaves col 13 ("Valuta" for Beløb) empty for cash-only
    transactions (interest, ASK tax, internal transfers). Those
    accounts are denominated in their basisvaluta — which is
    DKK in every account we own and is also the natural fallback
    for DK-locale Nordnet exports.
    """

    raw = row[_TXN_COL_AMOUNT_CCY].strip()
    return raw or "DKK"


def _extract_counter_account(text: str | None) -> str | None:
    if not text:
        return None
    m = _INTERNAL_COUNTER_RE.search(text)
    return m.group("account") if m else None


def _opt_str(s: str) -> str | None:
    s = s.strip()
    return s or None


def _decimal_or_none(s: str) -> Decimal | None:
    """Parse Nordnet's Danish-locale numbers (`1.234,56`) into Decimal."""

    s = s.strip()
    if not s:
        return None
    # Some price/quantity columns may use thousands separators '.'
    # in addition to a comma decimal mark; strip the former, swap
    # the latter.
    cleaned = s.replace(".", "").replace(",", ".") if "," in s else s
    try:
        return Decimal(cleaned)
    except InvalidOperation as e:
        raise ValueError(f"cannot parse decimal {s!r}") from e


def _date(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def _date_or_none(s: str) -> date | None:
    s = s.strip()
    if not s:
        return None
    return _date(s)


def _txn_sort_key(t: ParsedTransaction) -> tuple[date, str]:
    """Order transactions by value/bookkeeping date then nordnet_id.

    Tie-break by id so the choice of "latest" is deterministic for
    same-day rows; ids are monotonically increasing in practice.
    """

    primary = t.value_date or t.bookkeeping_date
    return (primary, t.nordnet_id)
