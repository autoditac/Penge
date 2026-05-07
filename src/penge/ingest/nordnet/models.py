"""Pydantic models for parsed Nordnet records.

These are the canonical shape produced by the parser. A separate
loader (future PR) translates them into rows of the `transaction`
and `holding_snapshot` tables.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    """Pydantic base — immutable, ignore unknown fields."""

    model_config = ConfigDict(frozen=True, extra="ignore", strict=False)


class ParsedTransaction(_Frozen):
    """One row of a Nordnet transaction CSV, in canonical form.

    Money fields are `Decimal` (parsed from comma-decimal strings).
    `account_number` is the raw Nordnet kontonummer; resolution to
    an internal `account.id` is the loader's job.
    """

    nordnet_id: str = Field(..., description="Nordnet's transaction id (unique).")
    bookkeeping_date: date = Field(..., description="Bogføringsdag.")
    trade_date: date | None = Field(None, description="Handelsdag.")
    value_date: date | None = Field(None, description="Valørdag.")
    account_number: str = Field(..., description="Nordnet depot/account number.")
    nordnet_type: str = Field(..., description="Raw Transaktionstype value.")
    canonical_kind: str = Field(..., description="Canonical kind from constants.py.")
    instrument_name: str | None = Field(None, description="Værdipapirer.")
    isin: str | None = Field(None, description="ISIN, when present.")
    quantity: Decimal | None = Field(None, description="Antal.")
    price: Decimal | None = Field(None, description="Kurs.")
    fees: Decimal | None = Field(None, description="Samlede afgifter.")
    amount: Decimal = Field(..., description="Beløb (signed).")
    amount_currency: str = Field(..., description="ISO-4217 of Beløb.")
    saldo: Decimal | None = Field(None, description="Running balance after this row.")
    fx_rate: Decimal | None = Field(None, description="Vekslingskurs (if present).")
    text: str | None = Field(None, description="Free-text Transaktionstekst.")
    counter_account: str | None = Field(
        None,
        description=(
            "For internal transfers, the other account number parsed "
            'from text like "Internal from 60109543".'
        ),
    )


class ParsedHolding(_Frozen):
    """One position in a Nordnet holdings CSV."""

    name: str = Field(..., description="Navn.")
    currency: str = Field(..., description="ISO-4217 from Valuta column.")
    quantity: Decimal = Field(..., description="Antal.")
    avg_cost: Decimal | None = Field(None, description="GAK / gns. kurs.")
    last_price: Decimal | None = Field(None, description="Seneste kurs.")
    market_value_dkk: Decimal | None = Field(None, description="Værdi DKK.")
    return_pct: Decimal | None = Field(None, description="Afkast (%).")
    return_dkk: Decimal | None = Field(None, description="Afkast DKK.")


class ParsedHoldingsFile(_Frozen):
    """A parsed holdings CSV plus the metadata extracted from its filename."""

    account_number: str
    as_of: date
    holdings: tuple[ParsedHolding, ...]


class ParsedCashBalance(_Frozen):
    """A derived cash sub-balance per (account, currency).

    Per ADR-0008, Nordnet does not export Valutakonto sub-balances.
    The most recent transaction `Saldo` per (account, currency) is
    treated as authoritative and modelled as a `holding_snapshot`
    row against synthetic instrument `CASH:<CCY>`.
    """

    account_number: str
    currency: str
    saldo: Decimal
    as_of: date = Field(..., description="value_date of the latest transaction used.")
