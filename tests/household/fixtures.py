"""Deterministic synthetic source facts for household integration tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


@dataclass(frozen=True, slots=True)
class HouseholdAccount:
    key: str
    entity_key: str
    name: str
    currency: str


@dataclass(frozen=True, slots=True)
class BankEntry:
    key: str
    account_key: str
    value_date: date
    amount: Decimal
    counterparty: str
    description: str


@dataclass(frozen=True, slots=True)
class PaypalDetail:
    entry_reference: str
    bank_entry_key: str
    amount: Decimal
    currency: str
    occurred_at: date
    merchant: str
    event_kind: str
    transaction_id: str


@dataclass(frozen=True, slots=True)
class SeededHousehold:
    entity_ids: dict[str, UUID]
    account_ids: dict[str, UUID]
    transaction_ids: dict[str, UUID]


ENTITIES = {
    "member-a": "Synthetic member A",
    "member-b": "Synthetic member B",
}

ACCOUNTS = (
    HouseholdAccount("eur-checking", "member-a", "Synthetic EUR checking", "EUR"),
    HouseholdAccount("dkk-checking", "member-b", "Synthetic DKK checking", "DKK"),
)

BANK_ENTRIES = (
    BankEntry(
        "before-first-fx",
        "eur-checking",
        date(2026, 5, 28),
        Decimal("-50.00"),
        "North Market",
        "Synthetic purchase before first ECB rate",
    ),
    BankEntry(
        "transfer-out",
        "eur-checking",
        date(2026, 5, 31),
        Decimal("-500.00"),
        "Synthetic household transfer",
        "Synthetic transfer to member B",
    ),
    BankEntry(
        "eur-salary",
        "eur-checking",
        date(2026, 6, 1),
        Decimal("3500.00"),
        "Synthetic employer",
        "Synthetic monthly salary",
    ),
    BankEntry(
        "supermarket-split",
        "eur-checking",
        date(2026, 6, 2),
        Decimal("-125.40"),
        "North Market",
        "Synthetic mixed supermarket purchase",
    ),
    BankEntry(
        "mixed-merchant-purchase",
        "eur-checking",
        date(2026, 6, 3),
        Decimal("-18.00"),
        "North Market",
        "Synthetic prepared-food purchase",
    ),
    BankEntry(
        "paypal-direct",
        "eur-checking",
        date(2026, 6, 3),
        Decimal("-23.45"),
        "PAYPAL *SYNTHETIC",
        "Synthetic PayPal purchase",
    ),
    BankEntry(
        "paypal-aggregate",
        "eur-checking",
        date(2026, 6, 4),
        Decimal("-42.00"),
        "PAYPAL *SYNTHETIC",
        "Synthetic aggregated PayPal purchase",
    ),
    BankEntry(
        "paypal-delayed",
        "eur-checking",
        date(2026, 6, 5),
        Decimal("-15.00"),
        "PAYPAL *SYNTHETIC",
        "Synthetic delayed PayPal settlement",
    ),
    BankEntry(
        "paypal-refund",
        "eur-checking",
        date(2026, 6, 6),
        Decimal("6.50"),
        "PAYPAL *SYNTHETIC",
        "Synthetic PayPal refund",
    ),
    BankEntry(
        "grocery-refund",
        "eur-checking",
        date(2026, 6, 6),
        Decimal("10.00"),
        "North Market",
        "Synthetic returned grocery item",
    ),
    BankEntry(
        "bank-fee",
        "eur-checking",
        date(2026, 6, 6),
        Decimal("-2.50"),
        "Synthetic bank",
        "Synthetic account service fee",
    ),
    BankEntry(
        "unclassified",
        "eur-checking",
        date(2026, 6, 7),
        Decimal("-7.00"),
        "Unknown synthetic vendor",
        "Synthetic unclassified purchase",
    ),
    BankEntry(
        "transfer-in",
        "dkk-checking",
        date(2026, 5, 31),
        Decimal("3720.00"),
        "Synthetic household transfer",
        "Synthetic transfer from member A",
    ),
    BankEntry(
        "dkk-salary",
        "dkk-checking",
        date(2026, 6, 1),
        Decimal("18000.00"),
        "Synthetic employer",
        "Synthetic monthly salary",
    ),
    BankEntry(
        "dkk-groceries",
        "dkk-checking",
        date(2026, 6, 2),
        Decimal("-149.00"),
        "Synthetic Grocer",
        "Synthetic grocery purchase",
    ),
)

PAYPAL_DETAILS = (
    PaypalDetail(
        "direct-purchase",
        "paypal-direct",
        Decimal("-23.45"),
        "EUR",
        date(2026, 6, 3),
        "Synthetic Books",
        "unknown",
        "synthetic-paypal-transaction-01",
    ),
    PaypalDetail(
        "aggregate-item-a",
        "paypal-aggregate",
        Decimal("-20.00"),
        "EUR",
        date(2026, 6, 3),
        "Synthetic Market",
        "unknown",
        "synthetic-paypal-transaction-02",
    ),
    PaypalDetail(
        "aggregate-item-b",
        "paypal-aggregate",
        Decimal("-22.00"),
        "EUR",
        date(2026, 6, 3),
        "Synthetic Travel",
        "unknown",
        "synthetic-paypal-transaction-03",
    ),
    PaypalDetail(
        "delayed-purchase",
        "paypal-delayed",
        Decimal("-15.00"),
        "EUR",
        date(2026, 6, 4),
        "Synthetic Stream",
        "unknown",
        "synthetic-paypal-transaction-04",
    ),
    PaypalDetail(
        "refund",
        "paypal-refund",
        Decimal("7.02"),
        "USD",
        date(2026, 6, 5),
        "Synthetic Books",
        "unknown",
        "synthetic-paypal-transaction-05",
    ),
)
PAYPAL_RENEWED_TRANSACTION_IDS = {"direct-purchase": "synthetic-paypal-transaction-renewed"}

PAYPAL_PRIMARY_IDENTIFICATION_HASH = "synthetic-paypal-primary-hash"
PAYPAL_SOURCE_ACCOUNT_ID = f"DE:{PAYPAL_PRIMARY_IDENTIFICATION_HASH}"
PAYPAL_SESSION_UIDS = ("synthetic-paypal-session-one", "synthetic-paypal-session-renewed")
PAYPAL_IDENTIFICATION_HASH_ALTERNATES = (
    "synthetic-paypal-alternate-one",
    "synthetic-paypal-alternate-renewed",
)

FX_RATES = (
    (date(2026, 5, 31), "DKK", Decimal("7.44000000")),
    (date(2026, 6, 1), "DKK", Decimal("7.45000000")),
    (date(2026, 6, 5), "USD", Decimal("1.08000000")),
)


def _stable_id(key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://penge.example/test/household/{key}")


def seed_household_source_facts(engine: Engine) -> SeededHousehold:
    """Insert deterministic synthetic bank facts into the migrated raw schema."""
    entity_ids = {key: _stable_id(f"entity/{key}") for key in ENTITIES}
    account_ids = {account.key: _stable_id(f"account/{account.key}") for account in ACCOUNTS}
    transaction_ids = {entry.key: _stable_id(f"transaction/{entry.key}") for entry in BANK_ENTRIES}

    with engine.begin() as connection:
        connection.execute(
            text("insert into entity (id, name, kind) values (:id, :name, 'person')"),
            [{"id": entity_ids[key], "name": name} for key, name in ENTITIES.items()],
        )
        connection.execute(
            text(
                "insert into account "
                "(id, entity_id, provider, external_id, name, kind, currency) "
                "values (:id, :entity_id, :provider, :external_id, :name, 'checking', :currency)"
            ),
            [
                {
                    "id": account_ids[account.key],
                    "entity_id": entity_ids[account.entity_key],
                    "provider": "gls" if account.currency == "EUR" else "lunar",
                    "external_id": f"household-{account.key}",
                    "name": account.name,
                    "currency": account.currency,
                }
                for account in ACCOUNTS
            ],
        )
        connection.execute(
            text(
                'insert into "transaction" '
                "(id, account_id, ts, value_date, kind, amount, counterparty, description, "
                "external_id) "
                "values (:id, :account_id, :ts, :value_date, :kind, :amount, :counterparty, "
                ":description, :external_id)"
            ),
            [
                {
                    "id": transaction_ids[entry.key],
                    "account_id": account_ids[entry.account_key],
                    "ts": datetime.combine(entry.value_date, datetime.min.time(), tzinfo=UTC),
                    "value_date": entry.value_date,
                    "kind": "deposit" if entry.amount > 0 else "withdrawal",
                    "amount": entry.amount,
                    "counterparty": entry.counterparty,
                    "description": entry.description,
                    "external_id": f"synthetic-{entry.key}",
                }
                for entry in BANK_ENTRIES
            ],
        )
        connection.execute(
            text(
                "insert into fx_rate (id, as_of, base_ccy, quote_ccy, rate, source) "
                "values (:id, :as_of, 'EUR', :quote_ccy, :rate, 'synthetic-test')"
            ),
            [
                {
                    "id": _stable_id(f"fx/eur-{quote_ccy.lower()}/{as_of.isoformat()}"),
                    "as_of": as_of,
                    "quote_ccy": quote_ccy,
                    "rate": rate,
                }
                for as_of, quote_ccy, rate in FX_RATES
            ],
        )

    return SeededHousehold(
        entity_ids=entity_ids,
        account_ids=account_ids,
        transaction_ids=transaction_ids,
    )
