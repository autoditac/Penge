"""Growney → Postgres loader.

Given one or more parsed Sutor Depotauszug PDFs and an entity
name, upsert everything (entity, account, instrument,
transaction, holding_snapshot) into the operational schema.

Idempotent — re-running with the same PDFs converges to the
same database state. Transactions get a synthesized
``external_id`` (sha256 of stable row fields) so the boundary
rows that appear on two consecutive quarterly statements only
land once.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import MetaData, Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from penge.ingest.growney.constants import (
    ACCOUNT_KIND_AKTIEDEPOT,
    PROVIDER,
)
from penge.ingest.growney.models import (
    ParsedDepotauszug,
    ParsedHolding,
    ParsedTransaction,
)
from penge.ingest.growney.parser import parse_depotauszug, synthesize_external_id

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine

log = logging.getLogger("penge.ingest.growney.loader")

CASH_INSTRUMENT_KIND = "cash"
CASH_TICKER_PREFIX = "CASH:"
SECURITY_INSTRUMENT_KIND = "security"
ACCOUNT_CURRENCY = "EUR"


@dataclass(frozen=True, slots=True)
class LoadResult:
    """Counts of upserts performed in one ``load_*(...)`` call."""

    entities: int
    accounts: int
    instruments: int
    transactions: int
    holding_snapshots: int

    def total(self) -> int:
        return (
            self.entities
            + self.accounts
            + self.instruments
            + self.transactions
            + self.holding_snapshots
        )


# --- public entrypoints ----------------------------------------------------


def load_files(
    engine: Engine,
    *,
    pdf_paths: Sequence[str | Path],
    entity_name: str,
    account_name: str | None = None,
) -> LoadResult:
    """Parse the given Sutor PDFs and upsert everything into Postgres."""

    parsed = [parse_depotauszug(p) for p in pdf_paths]
    return load_records(
        engine,
        depotauszuege=parsed,
        entity_name=entity_name,
        account_name=account_name,
    )


def load_records(
    engine: Engine,
    *,
    depotauszuege: Sequence[ParsedDepotauszug],
    entity_name: str,
    account_name: str | None = None,
) -> LoadResult:
    """Upsert pre-parsed Depotauszug records.

    All writes happen inside a single transaction; a failure
    rolls the whole load back.
    """

    if not depotauszuege:
        return LoadResult(0, 0, 0, 0, 0)

    meta = MetaData()
    tables = _reflect_tables(engine, meta)

    n_txn_total = 0
    n_hld_total = 0
    instrument_ids: dict[str, str] = {}
    cash_instrument_ids: dict[str, str] = {}
    account_ids: dict[str, str] = {}
    with engine.begin() as conn:
        entity_id = _upsert_entity(conn, tables["entity"], entity_name)
        for da in depotauszuege:
            account_id = account_ids.setdefault(
                da.depot_number,
                _upsert_account(
                    conn,
                    tables["account"],
                    entity_id=entity_id,
                    depot_number=da.depot_number,
                    account_name=account_name or _default_account_name(da),
                ),
            )
            for_isin = _upsert_security_instruments(
                conn, tables["instrument"], holdings=da.holdings
            )
            instrument_ids.update(for_isin)
            if da.cash_balance_eur != 0:
                cash_id = cash_instrument_ids.setdefault(
                    ACCOUNT_CURRENCY,
                    _upsert_cash_instrument(conn, tables["instrument"], ACCOUNT_CURRENCY),
                )
            else:
                cash_id = None
            n_txn_total += _upsert_transactions(
                conn,
                tables["transaction"],
                depot_number=da.depot_number,
                account_id=account_id,
                transactions=da.transactions,
                instrument_ids_by_isin=instrument_ids,
            )
            n_hld_total += _upsert_holding_snapshots(
                conn,
                tables["holding_snapshot"],
                account_id=account_id,
                as_of=da.as_of,
                holdings=da.holdings,
                cash_balance_eur=da.cash_balance_eur,
                cash_instrument_id=cash_id,
                instrument_ids_by_isin=instrument_ids,
            )

    return LoadResult(
        entities=1,
        accounts=len(account_ids),
        instruments=len(instrument_ids) + len(cash_instrument_ids),
        transactions=n_txn_total,
        holding_snapshots=n_hld_total,
    )


# --- reflection ------------------------------------------------------------


def _reflect_tables(engine: Engine, meta: MetaData) -> dict[str, Table]:
    return {
        name: Table(name, meta, autoload_with=engine)
        for name in ("entity", "account", "instrument", "transaction", "holding_snapshot")
    }


# --- entity / account ------------------------------------------------------


def _upsert_entity(conn: Connection, entity: Table, name: str) -> str:
    existing = conn.execute(
        select(entity.c.id).where(entity.c.name == name, entity.c.kind == "person").limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return str(existing)
    new_id = conn.execute(
        entity.insert().values(name=name, kind="person").returning(entity.c.id)
    ).scalar_one()
    return str(new_id)


def _upsert_account(
    conn: Connection,
    account: Table,
    *,
    entity_id: str,
    depot_number: str,
    account_name: str,
) -> str:
    stmt = pg_insert(account).values(
        entity_id=entity_id,
        provider=PROVIDER,
        external_id=depot_number,
        name=account_name,
        kind=ACCOUNT_KIND_AKTIEDEPOT,
        currency=ACCOUNT_CURRENCY,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="ux_account__provider_external_id",
        set_={
            "name": stmt.excluded.name,
            "kind": stmt.excluded.kind,
            "currency": stmt.excluded.currency,
            "entity_id": stmt.excluded.entity_id,
            "updated_at": _now(),
        },
    ).returning(account.c.id)
    return str(conn.execute(stmt).scalar_one())


def _default_account_name(da: ParsedDepotauszug) -> str:
    if da.strategy:
        return f"Growney {da.strategy}"
    return f"Growney {da.depot_number}"


# --- instruments -----------------------------------------------------------


def _upsert_security_instruments(
    conn: Connection,
    instrument: Table,
    *,
    holdings: Sequence[ParsedHolding],
) -> dict[str, str]:
    if not holdings:
        return {}
    payload = [
        {
            "isin": h.isin,
            "name": h.name,
            "kind": SECURITY_INSTRUMENT_KIND,
            # Holdings price column may be in USD; the security's
            # native currency is reported by Sutor on the unit price
            # column. ``Kurswert`` always lands in EUR.
            "currency": h.price_currency,
        }
        for h in holdings
    ]
    stmt = pg_insert(instrument).values(payload)
    stmt = stmt.on_conflict_do_update(
        constraint="ux_instrument__isin",
        set_={
            "name": stmt.excluded.name,
            "currency": stmt.excluded.currency,
            "updated_at": _now(),
        },
    ).returning(instrument.c.id, instrument.c.isin)
    rows = conn.execute(stmt).all()
    return {(r.isin or "").strip(): str(r.id) for r in rows}


def _upsert_cash_instrument(conn: Connection, instrument: Table, currency: str) -> str:
    ticker = f"{CASH_TICKER_PREFIX}{currency}"
    existing = conn.execute(
        select(instrument.c.id)
        .where((instrument.c.kind == CASH_INSTRUMENT_KIND) & (instrument.c.ticker == ticker))
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


# --- transactions ----------------------------------------------------------


def _upsert_transactions(
    conn: Connection,
    transaction: Table,
    *,
    depot_number: str,
    account_id: str,
    transactions: Sequence[ParsedTransaction],
    instrument_ids_by_isin: dict[str, str],
) -> int:
    if not transactions:
        return 0
    payload: list[dict[str, object]] = []
    for t in transactions:
        instrument_id = instrument_ids_by_isin.get(t.isin) if t.isin else None
        external_id = synthesize_external_id(
            depot_number=depot_number,
            bookkeeping_date=t.bookkeeping_date,
            value_date=t.value_date,
            sutor_type=t.sutor_type,
            isin=t.isin,
            quantity=t.quantity,
            net_amount_eur=t.net_amount_eur,
            description=t.description,
        )
        fee = t.fees_eur if t.fees_eur is not None else Decimal("0")
        tax = (t.capital_tax_eur or Decimal("0")) + (t.church_tax_eur or Decimal("0"))
        payload.append(
            {
                "account_id": account_id,
                "instrument_id": instrument_id,
                "ts": _to_utc_datetime(t.bookkeeping_date),
                "value_date": t.value_date,
                "kind": t.kind,
                "quantity": t.quantity,
                "price": t.unit_price,
                "amount": t.net_amount_eur,
                "fee": fee,
                "tax": tax,
                "fx_rate": t.fx_rate,
                "counterparty": t.venue,
                "description": t.description,
                "external_id": external_id,
            }
        )

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


# --- holding snapshots -----------------------------------------------------


def _upsert_holding_snapshots(
    conn: Connection,
    holding_snapshot: Table,
    *,
    account_id: str,
    as_of: date,
    holdings: Sequence[ParsedHolding],
    cash_balance_eur: Decimal,
    cash_instrument_id: str | None,
    instrument_ids_by_isin: dict[str, str],
) -> int:
    payload: list[dict[str, object]] = []
    for h in holdings:
        iid = instrument_ids_by_isin.get(h.isin)
        if iid is None:
            log.warning("skipping holding without instrument id: isin=%s", h.isin)
            continue
        payload.append(
            {
                "account_id": account_id,
                "instrument_id": iid,
                "as_of": as_of,
                "quantity": h.quantity,
                "price": h.price,
                "market_value": h.market_value_eur,
                "cost_basis": None,
            }
        )
    if cash_instrument_id is not None and cash_balance_eur != 0:
        payload.append(
            {
                "account_id": account_id,
                "instrument_id": cash_instrument_id,
                "as_of": as_of,
                "quantity": cash_balance_eur,
                "price": Decimal("1"),
                "market_value": cash_balance_eur,
                "cost_basis": cash_balance_eur,
            }
        )
    if not payload:
        return 0
    stmt = pg_insert(holding_snapshot).values(payload)
    stmt = stmt.on_conflict_do_update(
        constraint="ux_holding_snapshot__account_instrument_as_of",
        set_={
            "quantity": stmt.excluded.quantity,
            "price": stmt.excluded.price,
            "market_value": stmt.excluded.market_value,
            "cost_basis": stmt.excluded.cost_basis,
        },
    )
    conn.execute(stmt)
    return len(payload)


# --- helpers ---------------------------------------------------------------


def _to_utc_datetime(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "ACCOUNT_CURRENCY",
    "CASH_INSTRUMENT_KIND",
    "CASH_TICKER_PREFIX",
    "PROVIDER",
    "LoadResult",
    "load_files",
    "load_records",
]
