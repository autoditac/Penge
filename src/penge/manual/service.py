"""Persistence layer for manual cash + property entries.

Each public function takes an :class:`~sqlalchemy.engine.Engine`, opens
a single transaction, and performs the get-or-create + upsert sequence
needed to record one entry. All money columns are written as Decimals
to match the Numeric(20, 4) schema.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import MetaData, Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .entries import BalanceEntry, PropertyEntry

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine

log = logging.getLogger(__name__)

PROVIDER = "manual"
ENTITY_KIND = "person"
CASH_INSTRUMENT_KIND = "cash"
REAL_ESTATE_INSTRUMENT_KIND = "real_estate"


# --------------------------------------------------------------------------- #
# Reflection
# --------------------------------------------------------------------------- #


def _reflect(engine: Engine) -> dict[str, Table]:
    meta = MetaData()
    return {
        name: Table(name, meta, autoload_with=engine)
        for name in ("entity", "account", "instrument", "holding_snapshot")
    }


# --------------------------------------------------------------------------- #
# get-or-create helpers (pure-ish; take a Connection)
# --------------------------------------------------------------------------- #


def _get_or_create_entity(conn: Connection, entity_table: Table, name: str) -> str:
    existing = conn.execute(
        select(entity_table.c.id)
        .where(entity_table.c.name == name, entity_table.c.kind == ENTITY_KIND)
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return str(existing)
    new_id = conn.execute(
        entity_table.insert().values(name=name, kind=ENTITY_KIND).returning(entity_table.c.id)
    ).scalar_one()
    return str(new_id)


def _get_or_create_account(
    conn: Connection,
    account_table: Table,
    *,
    entity_id: str,
    account_name: str,
    kind: str,
    currency: str,
) -> str:
    """Get-or-create a manual-provider account keyed by ``(entity, name)``.

    The schema's unique constraint is on ``(provider, external_id)``;
    we use ``f"{entity_id}:{account_name}"`` as ``external_id`` so manual
    entries are stable across runs and disambiguated per owner. Concurrent
    calls are handled via a Postgres ``ON CONFLICT DO NOTHING`` upsert
    followed by a SELECT, mirroring the Nordnet loader.
    """
    external_id = f"{entity_id}:{account_name}"
    stmt = pg_insert(account_table).values(
        entity_id=entity_id,
        provider=PROVIDER,
        external_id=external_id,
        name=account_name,
        kind=kind,
        currency=currency,
    )
    stmt = stmt.on_conflict_do_nothing(constraint="ux_account__provider_external_id")
    conn.execute(stmt)
    account_id = conn.execute(
        select(account_table.c.id)
        .where(
            account_table.c.provider == PROVIDER,
            account_table.c.external_id == external_id,
        )
        .limit(1)
    ).scalar_one()
    return str(account_id)


def _get_or_create_instrument(
    conn: Connection,
    instrument_table: Table,
    *,
    name: str,
    kind: str,
    currency: str,
) -> str:
    """Get-or-create a synthetic instrument by (name, kind).

    Manual instruments have no ISIN/ticker, so the unique-by-ISIN
    index does not apply; we match on (name, kind, currency).
    """
    existing = conn.execute(
        select(instrument_table.c.id)
        .where(
            instrument_table.c.name == name,
            instrument_table.c.kind == kind,
            instrument_table.c.currency == currency,
        )
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return str(existing)
    new_id = conn.execute(
        instrument_table.insert()
        .values(name=name, kind=kind, currency=currency)
        .returning(instrument_table.c.id)
    ).scalar_one()
    return str(new_id)


def _upsert_holding_snapshot(
    conn: Connection,
    holding_snapshot_table: Table,
    *,
    account_id: str,
    instrument_id: str,
    as_of: date,
    market_value: Decimal,
) -> None:
    stmt = pg_insert(holding_snapshot_table).values(
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


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def record_cash_balance(engine: Engine, entry: BalanceEntry) -> None:
    """Upsert a cash-balance ``holding_snapshot`` row for ``entry``."""
    tables = _reflect(engine)
    with engine.begin() as conn:
        entity_id = _get_or_create_entity(conn, tables["entity"], entry.entity)
        account_id = _get_or_create_account(
            conn,
            tables["account"],
            entity_id=entity_id,
            account_name=entry.account_name,
            kind="cash",
            currency=entry.currency,
        )
        instrument_id = _get_or_create_instrument(
            conn,
            tables["instrument"],
            name=entry.account_name,
            kind=CASH_INSTRUMENT_KIND,
            currency=entry.currency,
        )
        _upsert_holding_snapshot(
            conn,
            tables["holding_snapshot"],
            account_id=account_id,
            instrument_id=instrument_id,
            as_of=entry.as_of,
            market_value=entry.balance,
        )
    log.info(
        "manual cash balance: entity=%s account=%s as_of=%s balance=%s %s",
        entry.entity,
        entry.account_name,
        entry.as_of,
        entry.balance,
        entry.currency,
    )


def record_property_value(engine: Engine, entry: PropertyEntry) -> None:
    """Upsert a real-estate ``holding_snapshot`` row for ``entry``."""
    tables = _reflect(engine)
    with engine.begin() as conn:
        entity_id = _get_or_create_entity(conn, tables["entity"], entry.entity)
        account_id = _get_or_create_account(
            conn,
            tables["account"],
            entity_id=entity_id,
            account_name=entry.account_name,
            kind="real_estate",
            currency=entry.currency,
        )
        instrument_id = _get_or_create_instrument(
            conn,
            tables["instrument"],
            name=entry.property_name,
            kind=REAL_ESTATE_INSTRUMENT_KIND,
            currency=entry.currency,
        )
        _upsert_holding_snapshot(
            conn,
            tables["holding_snapshot"],
            account_id=account_id,
            instrument_id=instrument_id,
            as_of=entry.as_of,
            market_value=entry.valuation,
        )
    log.info(
        "manual property value: entity=%s property=%s as_of=%s valuation=%s %s",
        entry.entity,
        entry.property_name,
        entry.as_of,
        entry.valuation,
        entry.currency,
    )
