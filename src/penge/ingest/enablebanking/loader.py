"""Generic Enable Banking → Postgres loader.

Provider-agnostic counterpart to the per-bank wrappers under
``penge.ingest.{gls,ebank,lunar}``. One ``load_account`` call:

1. fetches booked transactions and the latest balances for the
   account UID via the Enable Banking API,
2. ensures the operator's ``entity`` row, the bank's ``account`` row,
   and a synthetic ``CASH:<ccy>`` ``instrument`` row exist,
3. upserts each booked transaction keyed on
   ``(account_id, external_id)`` (the existing
   ``ux_transaction__account_id_external_id`` constraint), and
4. upserts a ``holding_snapshot`` row for the latest booked balance
   keyed on ``(account_id, instrument_id, as_of)``.

All writes happen inside a single transaction; on failure the load
rolls back. Re-running with the same upstream data converges to the
same DB state (idempotent).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import MetaData, Table, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from penge.ingest.enablebanking.mapping import (
    balance_to_market_value,
    external_id,
    transaction_to_row,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine

    from penge.ingest.enablebanking.client import Client
    from penge.ingest.enablebanking.models import BalancesResponse, Transaction

log = logging.getLogger("penge.ingest.enablebanking.loader")

ENTITY_KIND = "person"
ACCOUNT_KIND = "checking"
CASH_INSTRUMENT_KIND = "cash"
CASH_TICKER_PREFIX = "CASH:"


@dataclass(frozen=True, slots=True)
class LoadResult:
    """Counts of upserts performed by one ``load_account`` call."""

    transactions: int
    holding_snapshots: int


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def load_account(
    engine: Engine,
    *,
    provider: str,
    client: Client,
    account_uid: str,
    entity_name: str,
    account_name: str,
    currency: str = "EUR",
    iban: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    dk_tax_treatment: str | None = None,
) -> LoadResult:
    """Pull transactions + balance for one Enable Banking account and persist.

    ``account_uid`` is the per-session UUID returned by Enable Banking
    in :class:`AuthorizeSessionResponse.accounts[].uid` (or the
    ``accounts`` array of :class:`GetSessionResponse`). It is **not**
    the IBAN.

    ``provider`` is the canonical Penge provider slug
    (e.g. ``"gls"``, ``"ebank"``, ``"lunar"``) and is stored verbatim
    on the ``account`` row.

    ``dk_tax_treatment`` tags the account with a Danish tax regime
    when applicable (e.g. ``"aktiesparekonto"`` for Lunar ASK
    subaccounts). ``None`` leaves the column unset / clears it on
    re-sync so a mistagged account can be corrected upstream.
    """
    txns = client.get_account_transactions(
        account_uid,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
    ).transactions
    balances = client.get_account_balances(account_uid)

    return _persist(
        engine,
        provider=provider,
        transactions=txns,
        balances=balances,
        entity_name=entity_name,
        account_external_id=account_uid,
        account_name=account_name,
        currency=currency,
        iban=iban,
        dk_tax_treatment=dk_tax_treatment,
    )


def _persist(
    engine: Engine,
    *,
    provider: str,
    transactions: list[Transaction],
    balances: BalancesResponse,
    entity_name: str,
    account_external_id: str,
    account_name: str,
    currency: str,
    iban: str | None,
    dk_tax_treatment: str | None,
) -> LoadResult:
    tables = _reflect(engine)
    with engine.begin() as conn:
        entity_id = _get_or_create_entity(conn, tables["entity"], entity_name)
        account_id = _get_or_create_account(
            conn,
            tables["account"],
            provider=provider,
            entity_id=entity_id,
            external_id=account_external_id,
            name=account_name,
            currency=currency,
            iban=iban,
            dk_tax_treatment=dk_tax_treatment,
        )
        instrument_id = _get_or_create_cash_instrument(
            conn,
            tables["instrument"],
            currency=currency,
        )
        n_txn = _upsert_transactions(
            conn,
            tables["transaction"],
            provider=provider,
            transactions=transactions,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        n_snap = _upsert_balance_snapshot(
            conn,
            tables["holding_snapshot"],
            balances=balances,
            account_id=account_id,
            instrument_id=instrument_id,
        )
    log.info(
        "Enable Banking load: provider=%s account=%s booked=%d snapshots=%d",
        provider,
        account_name,
        n_txn,
        n_snap,
    )
    return LoadResult(transactions=n_txn, holding_snapshots=n_snap)


# --------------------------------------------------------------------------- #
# Reflection
# --------------------------------------------------------------------------- #


def _reflect(engine: Engine) -> dict[str, Table]:
    meta = MetaData()
    return {
        name: Table(name, meta, autoload_with=engine)
        for name in ("entity", "account", "instrument", "transaction", "holding_snapshot")
    }


# --------------------------------------------------------------------------- #
# get-or-create helpers
# --------------------------------------------------------------------------- #


def _get_or_create_entity(conn: Connection, entity: Table, name: str) -> str:
    existing = conn.execute(
        select(entity.c.id).where(entity.c.name == name, entity.c.kind == ENTITY_KIND).limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return str(existing)
    new_id = conn.execute(
        entity.insert().values(name=name, kind=ENTITY_KIND).returning(entity.c.id)
    ).scalar_one()
    return str(new_id)


def _get_or_create_account(
    conn: Connection,
    account: Table,
    *,
    provider: str,
    entity_id: str,
    external_id: str,
    name: str,
    currency: str,
    iban: str | None,
    dk_tax_treatment: str | None,
) -> str:
    """Upsert the account keyed on ``(provider, external_id)``."""
    stmt = pg_insert(account).values(
        entity_id=entity_id,
        provider=provider,
        external_id=external_id,
        name=name,
        kind=ACCOUNT_KIND,
        currency=currency,
        iban=iban,
        dk_tax_treatment=dk_tax_treatment,
    )
    # Refresh metadata on conflict so renames / IBAN updates / currency
    # corrections from upstream propagate to existing rows.
    stmt = stmt.on_conflict_do_update(
        constraint="ux_account__provider_external_id",
        set_={
            "entity_id": stmt.excluded.entity_id,
            "name": stmt.excluded.name,
            "currency": stmt.excluded.currency,
            "iban": stmt.excluded.iban,
            "dk_tax_treatment": stmt.excluded.dk_tax_treatment,
            "updated_at": func.now(),
        },
    )
    conn.execute(stmt)
    account_id = conn.execute(
        select(account.c.id)
        .where(account.c.provider == provider, account.c.external_id == external_id)
        .limit(1)
    ).scalar_one()
    return str(account_id)


def _get_or_create_cash_instrument(
    conn: Connection,
    instrument: Table,
    *,
    currency: str,
) -> str:
    """One ``CASH:<CCY>`` synthetic instrument per currency."""
    ticker = f"{CASH_TICKER_PREFIX}{currency}"
    existing = conn.execute(
        select(instrument.c.id)
        .where(
            instrument.c.kind == CASH_INSTRUMENT_KIND,
            instrument.c.ticker == ticker,
        )
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return str(existing)
    new_id = conn.execute(
        instrument.insert()
        .values(
            kind=CASH_INSTRUMENT_KIND,
            ticker=ticker,
            name=f"Cash ({currency})",
            currency=currency,
            isin=None,
        )
        .returning(instrument.c.id)
    ).scalar_one()
    return str(new_id)


# --------------------------------------------------------------------------- #
# Upserts
# --------------------------------------------------------------------------- #


def _upsert_transactions(
    conn: Connection,
    transaction: Table,
    *,
    provider: str,
    transactions: list[Transaction],
    account_id: str,
    instrument_id: str,
) -> int:
    payload: list[dict[str, object]] = []
    for t in transactions:
        if external_id(t) is None:
            # Avoid logging the full Transaction model: it can contain
            # counterparty names, IBANs, and amounts (PII).
            log.warning(
                "skipping %s transaction without stable id (booking_date=%s)",
                provider,
                t.booking_date,
            )
            continue
        payload.append(transaction_to_row(t, account_id=account_id, instrument_id=instrument_id))
    if not payload:
        return 0

    stmt = pg_insert(transaction).values(payload)
    stmt = stmt.on_conflict_do_update(
        constraint="ux_transaction__account_id_external_id",
        set_={
            "instrument_id": stmt.excluded.instrument_id,
            "ts": stmt.excluded.ts,
            "value_date": stmt.excluded.value_date,
            "kind": stmt.excluded.kind,
            "quantity": stmt.excluded.quantity,
            "price": stmt.excluded.price,
            "amount": stmt.excluded.amount,
            "fee": stmt.excluded.fee,
            "tax": stmt.excluded.tax,
            "fx_rate": stmt.excluded.fx_rate,
            "counterparty": stmt.excluded.counterparty,
            "description": stmt.excluded.description,
        },
    )
    conn.execute(stmt)
    return len(payload)


def _upsert_balance_snapshot(
    conn: Connection,
    holding_snapshot: Table,
    *,
    balances: BalancesResponse,
    account_id: str,
    instrument_id: str,
) -> int:
    picked = balance_to_market_value(balances)
    if picked is None:
        return 0
    market_value, as_of = picked
    stmt = pg_insert(holding_snapshot).values(
        account_id=account_id,
        instrument_id=instrument_id,
        as_of=as_of,
        quantity=Decimal("1"),
        market_value=market_value,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="ux_holding_snapshot__account_instrument_as_of",
        set_={
            "quantity": stmt.excluded.quantity,
            "market_value": stmt.excluded.market_value,
            "price": None,
            "cost_basis": None,
        },
    )
    conn.execute(stmt)
    return 1
