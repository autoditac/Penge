"""Vocabulary for Nordnet ingest — see ADR-0008.

These are the only string constants the rest of the codebase
(loader, dbt staging, marts, tax modules) should match against.
Do not introduce new account-kind or transaction-kind values
without updating ADR-0008.
"""

from __future__ import annotations

from typing import Final

# --- account.kind vocabulary -------------------------------------------------

ACCOUNT_KIND_AKTIEDEPOT: Final = "aktiedepot"
"""AKT — regular taxable securities depot (realisation method)."""

ACCOUNT_KIND_AKTIESPAREKONTO: Final = "aktiesparekonto"
"""ASK — Danish capital-tax-advantaged shell (lagerbeskatning)."""

ACCOUNT_KIND_OPSPARINGSKONTO: Final = "opsparingskonto"
"""OPS — pure cash savings account."""

ACCOUNT_KINDS: Final = frozenset(
    {
        ACCOUNT_KIND_AKTIEDEPOT,
        ACCOUNT_KIND_AKTIESPAREKONTO,
        ACCOUNT_KIND_OPSPARINGSKONTO,
    }
)

# --- transaction.kind vocabulary --------------------------------------------

TXN_KIND_BUY: Final = "buy"
TXN_KIND_SELL: Final = "sell"
TXN_KIND_DIVIDEND: Final = "dividend"
TXN_KIND_DEPOSIT: Final = "deposit"
TXN_KIND_WITHDRAWAL: Final = "withdrawal"
TXN_KIND_INTERNAL_TRANSFER: Final = "internal_transfer"
TXN_KIND_CASH_INTEREST: Final = "cash_interest"
TXN_KIND_TAX_ASK_CHARGE: Final = "tax_ask_charge"
TXN_KIND_TAX_ASK_PAYMENT: Final = "tax_ask_payment"

# --- mapping: Nordnet Transaktionstype -> canonical kind --------------------

# `INDSÆTTELSE` and `HÆVNING` map to either `internal_transfer` or
# `deposit`/`withdrawal` depending on whether `Transaktionstekst` looks
# like "Internal (from|to) NNN". The parser does that decision; this
# table only handles the unambiguous cases.

NORDNET_TXN_TYPE_MAP: Final[dict[str, str]] = {
    "KØBT": TXN_KIND_BUY,
    "SOLGT": TXN_KIND_SELL,
    "UDBYTTE": TXN_KIND_DIVIDEND,
    "INDBETALING": TXN_KIND_DEPOSIT,
    "KREDITRENTE": TXN_KIND_CASH_INTEREST,
    "AFKASTSKAT ASK": TXN_KIND_TAX_ASK_CHARGE,
    "SKATTEINDBETALING ASK": TXN_KIND_TAX_ASK_PAYMENT,
}
"""Direct map of Nordnet's Transaktionstype to canonical kinds.

`INDSÆTTELSE` / `HÆVNING` are intentionally absent — the parser
inspects `Transaktionstekst` to choose between
`internal_transfer` and `deposit`/`withdrawal`.
"""

# --- file encoding ----------------------------------------------------------

NORDNET_CSV_ENCODING: Final = "utf-16-le"
"""All Nordnet exports are UTF-16LE with a BOM."""

NORDNET_CSV_DELIMITER: Final = "\t"
"""Tab-separated despite the .csv extension."""

NORDNET_BOM: Final = "\ufeff"
"""Stripped from the first cell of the header row."""
