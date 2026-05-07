"""Test fixture builders for Nordnet CSV exports.

Synthetic, anonymised data only. Real exports never make it into
the repo. Files are materialised under ``tmp_path`` at test time
to avoid committing binary UTF-16 fixtures.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

# ---- transactions ----------------------------------------------------------

TXN_HEADER: tuple[str, ...] = (
    "Id",
    "Bogføringsdag",
    "Handelsdag",
    "Valørdag",
    "Depot",
    "Transaktionstype",
    "Værdipapirer",
    "ISIN",
    "Antal",
    "Kurs",
    "Rente",
    "Samlede afgifter",
    "Valuta",
    "Beløb",
    "Valuta",
    "Indkøbsværdi",
    "Valuta",
    "Resultat",
    "Valuta",
    "Totalt antal",
    "Saldo",
    "Vekslingskurs",
    "Transaktionstekst",
    "Makuleringsdato",
    "Notanummer",
    "Verifikationsnummer",
    "Kurtage",
    "Valuta",
    "Middelkurs",
    "Oprindelig rente",
)
assert len(TXN_HEADER) == 30


def txn_row(
    *,
    id_: str,
    book_date: str,
    trade_date: str = "",
    value_date: str = "",
    depot: str,
    type_: str,
    name: str = "",
    isin: str = "",
    quantity: str = "",
    price: str = "",
    fees: str = "",
    amount_ccy: str = "",
    amount: str,
    saldo: str = "",
    fx: str = "",
    text: str = "",
) -> tuple[str, ...]:
    """Build a 30-field transaction row.

    Only the fields used by the parser are exposed here; the rest
    default to empty strings, which matches what real Nordnet
    exports look like for non-trade transactions.
    """

    row = [""] * 30
    row[0] = id_
    row[1] = book_date
    row[2] = trade_date
    row[3] = value_date
    row[4] = depot
    row[5] = type_
    row[6] = name
    row[7] = isin
    row[8] = quantity
    row[9] = price
    row[11] = fees
    row[12] = amount_ccy
    row[13] = amount
    row[20] = saldo
    row[21] = fx
    row[22] = text
    return tuple(row)


# ---- holdings --------------------------------------------------------------

HLD_HEADER: tuple[str, ...] = (
    "Navn",
    "Valuta",
    "Antal",
    "GAK/gns. kurs",
    "I dag %",
    "Seneste kurs",
    "Belåningsværdi DKK",
    "Værdi DKK",
    "Afkast",
    "Afkast DKK",
)
assert len(HLD_HEADER) == 10


def hld_row(
    *,
    name: str,
    currency: str,
    quantity: str,
    avg_cost: str = "",
    today_pct: str = "",
    last_price: str = "",
    loan_value_dkk: str = "",
    value_dkk: str = "",
    return_pct: str = "",
    return_dkk: str = "",
) -> tuple[str, ...]:
    return (
        name,
        currency,
        quantity,
        avg_cost,
        today_pct,
        last_price,
        loan_value_dkk,
        value_dkk,
        return_pct,
        return_dkk,
    )


# ---- file writer -----------------------------------------------------------


def write_nordnet_csv(
    path: Path,
    rows: Sequence[Sequence[str]],
) -> Path:
    """Write rows as UTF-16LE BOM tab-separated CSV (Nordnet's format).

    Lines are terminated with CRLF to match real exports. Returns
    the path for chaining.
    """

    body = "\r\n".join("\t".join(r) for r in rows) + "\r\n"
    payload = "\ufeff" + body
    path.write_bytes(payload.encode("utf-16-le"))
    return path
