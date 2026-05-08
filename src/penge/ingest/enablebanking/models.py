"""Pydantic models for Enable Banking responses.

Only the subset Penge actually consumes is modelled. ``extra='ignore'``
keeps these forward-compatible with new optional fields the API may
add. Decimal is used for money so we never lose precision via float.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- #
# Generic shapes
# --------------------------------------------------------------------------- #


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)


class Aspsp(_Frozen):
    name: str
    country: str  # ISO 3166-1 alpha-2


class Amount(_Frozen):
    amount: Decimal
    currency: str  # ISO 4217


class AccountIdentification(_Frozen):
    iban: str | None = None


class PartyIdentification(_Frozen):
    name: str | None = None


class BankTransactionCode(_Frozen):
    description: str | None = None
    code: str | None = None
    sub_code: str | None = None


# --------------------------------------------------------------------------- #
# Auth + session
# --------------------------------------------------------------------------- #

# ISO 20022 transaction status codes used by Enable Banking. Penge
# ingests booked entries only — pending balances are surfaced via the
# balance endpoint.
TransactionStatus = Literal["BOOK", "CNCL", "HOLD", "OTHR", "PDNG", "RJCT", "SCHD"]
CreditDebit = Literal["CRDT", "DBIT"]
PsuType = Literal["personal", "business"]
SessionStatus = Literal[
    "AUTHORIZED",
    "CANCELLED",
    "CLOSED",
    "EXPIRED",
    "INVALID",
    "PENDING_AUTHORIZATION",
    "RETURNED_FROM_BANK",
    "REVOKED",
]


class StartAuthorizationResponse(_Frozen):
    url: str  # PSU is redirected here
    authorization_id: str
    psu_id_hash: str | None = None


class AccountResource(_Frozen):
    """Account as exposed by ``POST /sessions`` and ``GET /sessions/{id}``."""

    uid: str | None = None  # the value to use against /accounts/{id}/...
    name: str | None = None
    details: str | None = None
    product: str | None = None
    currency: str | None = None
    cash_account_type: str | None = None
    account_id: AccountIdentification | None = None
    identification_hash: str | None = None


class Access(_Frozen):
    valid_until: datetime
    accounts: list[AccountIdentification] | None = None
    balances: bool | None = None
    transactions: bool | None = None


class AuthorizeSessionResponse(_Frozen):
    session_id: str
    accounts: list[AccountResource]
    aspsp: Aspsp
    psu_type: PsuType
    access: Access


class GetSessionResponse(_Frozen):
    status: SessionStatus
    accounts: list[str]  # list of account UIDs
    accounts_data: list[AccountResource]
    aspsp: Aspsp
    psu_type: PsuType
    access: Access
    created: datetime
    authorized: datetime | None = None
    closed: datetime | None = None


# --------------------------------------------------------------------------- #
# Balances + transactions
# --------------------------------------------------------------------------- #


class Balance(_Frozen):
    name: str
    balance_amount: Amount
    # ISO 20022 codes: CLBD (closing booked), CLAV, ITBD, ITAV, etc.
    balance_type: str
    last_change_date_time: datetime | None = None
    reference_date: date | None = None
    last_committed_transaction: str | None = None


class BalancesResponse(_Frozen):
    balances: list[Balance]


class Transaction(_Frozen):
    """Berlin Group / ISO 20022 transaction.

    ``transaction_amount.amount`` is always positive; the sign comes
    from ``credit_debit_indicator``. ``entry_reference`` is the stable
    per-account dedup key (immutable across sessions per the API
    spec). ``transaction_id`` is for detail fetching only and may
    change between requests — do not use it as a primary key.
    """

    entry_reference: str | None = None
    transaction_id: str | None = None
    merchant_category_code: str | None = None
    transaction_amount: Amount
    creditor: PartyIdentification | None = None
    debtor: PartyIdentification | None = None
    creditor_account: AccountIdentification | None = None
    debtor_account: AccountIdentification | None = None
    bank_transaction_code: BankTransactionCode | None = None
    credit_debit_indicator: CreditDebit
    status: TransactionStatus
    booking_date: date | None = None
    value_date: date | None = None
    transaction_date: date | None = None
    remittance_information: list[str] = Field(default_factory=list)
    note: str | None = None


class TransactionsResponse(_Frozen):
    transactions: list[Transaction]
    continuation_key: str | None = None
