"""Validated input records for the manual-entry CLI.

Both entry types are pure value objects; persistence lives in
:mod:`penge.manual.service`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

_CURRENCY_LEN = 3


def _validate_currency(currency: str) -> str:
    if len(currency) != _CURRENCY_LEN or not currency.isalpha():
        raise ValueError(f"currency must be a 3-letter ISO code, got {currency!r}")
    return currency.upper()


def _validate_non_empty(field: str, value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} must not be empty")
    return cleaned


def _validate_non_negative(field: str, value: Decimal) -> Decimal:
    if value < 0:
        raise ValueError(f"{field} must be >= 0, got {value}")
    return value


@dataclass(frozen=True, slots=True)
class BalanceEntry:
    """Record of a cash-account balance at a point in time.

    Cash is modelled as a synthetic ``instrument(kind='cash')`` so it
    fits the existing ``holding_snapshot`` schema (quantity = 1,
    market_value = balance).
    """

    entity: str
    account_name: str
    currency: str
    as_of: date
    balance: Decimal
    note: str | None = None

    def __post_init__(self) -> None:
        # ``frozen=True`` blocks plain assignment; use object.__setattr__
        # to write back the normalised values.
        object.__setattr__(self, "entity", _validate_non_empty("entity", self.entity))
        object.__setattr__(
            self, "account_name", _validate_non_empty("account_name", self.account_name)
        )
        object.__setattr__(self, "currency", _validate_currency(self.currency))
        object.__setattr__(self, "balance", _validate_non_negative("balance", self.balance))


@dataclass(frozen=True, slots=True)
class PropertyEntry:
    """Record of a real-estate valuation at a point in time.

    Real estate is modelled as ``instrument(kind='real_estate')`` with
    a ``holding_snapshot`` row whose quantity is 1 and market_value is
    the valuation.
    """

    entity: str
    account_name: str
    property_name: str
    currency: str
    as_of: date
    valuation: Decimal
    note: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity", _validate_non_empty("entity", self.entity))
        object.__setattr__(
            self, "account_name", _validate_non_empty("account_name", self.account_name)
        )
        object.__setattr__(
            self, "property_name", _validate_non_empty("property_name", self.property_name)
        )
        object.__setattr__(self, "currency", _validate_currency(self.currency))
        object.__setattr__(self, "valuation", _validate_non_negative("valuation", self.valuation))
