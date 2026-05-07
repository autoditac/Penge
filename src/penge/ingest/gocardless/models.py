"""Pydantic models for the GoCardless Bank Account Data API.

The upstream schema is large; we model only the fields Penge actually
consumes. Unknown fields are silently dropped (``model_config`` allows
extras to keep the parser forward-compatible with new API additions).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class Token(_Base):
    """Access + refresh token pair returned by ``/token/new/``."""

    access: str
    access_expires: int = Field(description="Seconds until access expires.")
    refresh: str
    refresh_expires: int = Field(description="Seconds until refresh expires.")


class Institution(_Base):
    """A bank entry from ``/institutions/``."""

    id: str
    name: str
    bic: str | None = None
    transaction_total_days: str | None = None
    countries: tuple[str, ...] = ()


class Requisition(_Base):
    """End-user agreement linking accounts after consent."""

    id: str
    status: str
    institution_id: str
    reference: str | None = None
    link: str | None = None
    accounts: tuple[str, ...] = ()
    created: datetime | None = None


class _Amount(_Base):
    amount: Decimal
    currency: str


class Balance(_Base):
    """One balance row from ``/accounts/{id}/balances/``."""

    balance_amount: _Amount = Field(alias="balanceAmount")
    balance_type: str = Field(alias="balanceType")
    reference_date: date | None = Field(default=None, alias="referenceDate")


class AccountBalances(_Base):
    """Top-level shape of ``/accounts/{id}/balances/``."""

    balances: tuple[Balance, ...]


class Transaction(_Base):
    """One booked or pending transaction.

    GoCardless returns highly heterogeneous shapes per institution, so
    we keep almost every field optional and let downstream code do the
    cleaning.
    """

    transaction_id: str | None = Field(default=None, alias="transactionId")
    internal_transaction_id: str | None = Field(default=None, alias="internalTransactionId")
    booking_date: date | None = Field(default=None, alias="bookingDate")
    value_date: date | None = Field(default=None, alias="valueDate")
    transaction_amount: _Amount = Field(alias="transactionAmount")
    creditor_name: str | None = Field(default=None, alias="creditorName")
    debtor_name: str | None = Field(default=None, alias="debtorName")
    remittance_information_unstructured: str | None = Field(
        default=None, alias="remittanceInformationUnstructured"
    )
    bank_transaction_code: str | None = Field(default=None, alias="bankTransactionCode")
    proprietary_bank_transaction_code: str | None = Field(
        default=None, alias="proprietaryBankTransactionCode"
    )


class TransactionsPage(_Base):
    """Top-level shape of ``/accounts/{id}/transactions/``."""

    booked: tuple[Transaction, ...] = ()
    pending: tuple[Transaction, ...] = ()


class AccountDetailsBody(_Base):
    """Inner ``account`` object from ``/accounts/{id}/details/``.

    Shape varies per institution; we model the few fields we use and
    drop the rest.
    """

    iban: str | None = None
    name: str | None = None
    currency: str | None = None
    owner_name: str | None = Field(default=None, alias="ownerName")
    product: str | None = None
    resource_id: str | None = Field(default=None, alias="resourceId")


class AccountDetails(_Base):
    """Top-level wrapper of ``/accounts/{id}/details/``."""

    account: AccountDetailsBody
