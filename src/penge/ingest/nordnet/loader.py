"""Nordnet → Postgres loader.

Given a transaction CSV path, zero-or-more holdings CSV paths and an
``AccountsConfig``, upsert canonical records into the operational
tables (``entity``, ``account``, ``instrument``, ``transaction``,
``holding_snapshot``).

Idempotent — re-running with the same inputs converges to the
same database state. ``ON CONFLICT DO UPDATE`` is used on the
canonical natural keys, so business columns may be overwritten
but row identity is preserved.

Internal-transfer rows (per ADR-0008) are written on **both** sides
of the transfer with ``kind='internal_transfer'`` and the
counter-account preserved on ``counterparty``. Downstream marts
filter on ``kind`` to avoid double-counting cashflows; per-account
running balances therefore still reconcile with Nordnet's *Saldo*.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import MetaData, Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from penge.ingest.nordnet.config import AccountsConfig
from penge.ingest.nordnet.constants import TXN_KIND_INTERNAL_TRANSFER
from penge.ingest.nordnet.models import (
    ParsedCashBalance,
    ParsedHolding,
    ParsedHoldingsFile,
    ParsedTransaction,
)
from penge.ingest.nordnet.parser import (
    UnknownAccountError,
    derive_cash_balances,
    instrument_map_from_transactions,
    parse_holdings_file,
    parse_transactions,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine

log = logging.getLogger("penge.ingest.nordnet.loader")

PROVIDER = "nordnet"
CASH_INSTRUMENT_KIND = "cash"
CASH_TICKER_PREFIX = "CASH:"


# --------------------------------------------------------------------------- #
# Result struct
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class LoadResult:
    """Counts of upserts performed in one ``load(...)`` call."""

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


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #


def load_files(
    engine: Engine,
    *,
    transactions_csv: str | Path,
    holdings_csvs: Sequence[str | Path],
    accounts_config: AccountsConfig,
) -> LoadResult:
    """Parse the given CSVs and upsert everything into Postgres.

    All writes happen inside a single transaction. On failure the
    whole load rolls back.
    """

    txns: list[ParsedTransaction] = list(parse_transactions(transactions_csv))
    holdings: list[ParsedHoldingsFile] = [parse_holdings_file(p) for p in holdings_csvs]
    return load_records(
        engine,
        transactions=txns,
        holdings=holdings,
        accounts_config=accounts_config,
    )


def load_records(
    engine: Engine,
    *,
    transactions: Sequence[ParsedTransaction],
    holdings: Sequence[ParsedHoldingsFile],
    accounts_config: AccountsConfig,
) -> LoadResult:
    """Upsert pre-parsed records. Useful for tests and re-runs."""

    _check_accounts_known(transactions, holdings, accounts_config)

    isin_by_name = instrument_map_from_transactions(transactions)
    cash_balances = derive_cash_balances(transactions)

    meta = MetaData()
    tables = _reflect_tables(engine, meta)

    with engine.begin() as conn:
        entity_ids = _upsert_entities(conn, tables["entity"], accounts_config)
        account_ids = _upsert_accounts(conn, tables["account"], accounts_config, entity_ids)
        instrument_ids = _upsert_instruments(
            conn,
            tables["instrument"],
            isin_by_name=isin_by_name,
            transactions=transactions,
            holdings=holdings,
            cash_balances=cash_balances,
        )
        n_txn = _upsert_transactions(
            conn,
            tables["transaction"],
            transactions=transactions,
            account_ids=account_ids,
            instrument_ids_by_isin=instrument_ids.by_isin,
        )
        n_hld = _upsert_holding_snapshots(
            conn,
            tables["holding_snapshot"],
            holdings=holdings,
            cash_balances=cash_balances,
            account_ids=account_ids,
            instrument_ids_by_isin=instrument_ids.by_isin,
            instrument_ids_by_cash_ticker=instrument_ids.by_cash_ticker,
            isin_by_name=isin_by_name,
        )

    return LoadResult(
        entities=len(entity_ids),
        accounts=len(account_ids),
        instruments=len(instrument_ids.by_isin) + len(instrument_ids.by_cash_ticker),
        transactions=n_txn,
        holding_snapshots=n_hld,
    )


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def _check_accounts_known(
    transactions: Iterable[ParsedTransaction],
    holdings: Iterable[ParsedHoldingsFile],
    cfg: AccountsConfig,
) -> None:
    """Fail fast when a record references an unconfigured account."""

    seen: set[str] = set()
    for t in transactions:
        seen.add(t.account_number)
    for h in holdings:
        seen.add(h.account_number)
    missing = sorted(n for n in seen if cfg.by_number(n) is None)
    if missing:
        raise UnknownAccountError(f"Nordnet accounts not present in config: {missing!r}")


# --------------------------------------------------------------------------- #
# Reflection
# --------------------------------------------------------------------------- #


def _reflect_tables(engine: Engine, meta: MetaData) -> dict[str, Table]:
    return {
        name: Table(name, meta, autoload_with=engine)
        for name in (
            "entity",
            "account",
            "instrument",
            "transaction",
            "holding_snapshot",
        )
    }


# --------------------------------------------------------------------------- #
# entity
# --------------------------------------------------------------------------- #


def _upsert_entities(conn: Connection, entity: Table, cfg: AccountsConfig) -> dict[str, str]:
    """Return ``{entity_name: entity.id}`` for every entity in cfg.

    The schema has no unique index on ``entity.name`` (entities can
    legitimately share a name across kinds in some scenarios). We
    therefore SELECT-or-INSERT inside the load transaction. The
    loader only deals with `kind='person'` entities; richer entity
    types are out of scope.
    """

    out: dict[str, str] = {}
    distinct_names = sorted({a.entity for a in cfg.accounts})
    for name in distinct_names:
        existing = conn.execute(
            select(entity.c.id).where(entity.c.name == name, entity.c.kind == "person").limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            out[name] = str(existing)
            continue
        new_id = conn.execute(
            entity.insert().values(name=name, kind="person").returning(entity.c.id)
        ).scalar_one()
        out[name] = str(new_id)
    return out


# --------------------------------------------------------------------------- #
# account
# --------------------------------------------------------------------------- #


def _upsert_accounts(
    conn: Connection,
    account: Table,
    cfg: AccountsConfig,
    entity_ids: dict[str, str],
) -> dict[str, str]:
    """Return ``{kontonummer: account.id}`` for every configured account."""

    payload = [
        {
            "entity_id": entity_ids[a.entity],
            "provider": PROVIDER,
            "external_id": a.number,
            "name": a.name or f"Nordnet {a.kind} {a.number}",
            "kind": a.kind,
            "currency": a.currency,
        }
        for a in cfg.accounts
    ]
    if not payload:
        return {}

    stmt = pg_insert(account).values(payload)
    stmt = stmt.on_conflict_do_update(
        constraint="ux_account__provider_external_id",
        set_={
            "name": stmt.excluded.name,
            "kind": stmt.excluded.kind,
            "currency": stmt.excluded.currency,
            "entity_id": stmt.excluded.entity_id,
            "updated_at": _now(),
        },
    ).returning(account.c.id, account.c.external_id)
    rows = conn.execute(stmt).all()
    return {r.external_id: str(r.id) for r in rows}


# --------------------------------------------------------------------------- #
# instrument
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _InstrumentIds:
    by_isin: dict[str, str]  # ISIN -> instrument.id
    by_cash_ticker: dict[str, str]  # 'CASH:<CCY>' -> instrument.id


def _upsert_instruments(
    conn: Connection,
    instrument: Table,
    *,
    isin_by_name: dict[str, str],
    transactions: Sequence[ParsedTransaction],
    holdings: Sequence[ParsedHoldingsFile],
    cash_balances: Sequence[ParsedCashBalance],
) -> _InstrumentIds:
    by_isin = _upsert_security_instruments(
        conn, instrument, isin_by_name=isin_by_name, holdings=holdings
    )
    by_cash_ticker = _upsert_cash_instruments(conn, instrument, cash_balances)
    _ = transactions  # currently unused; kept for future ticker-only securities
    return _InstrumentIds(by_isin=by_isin, by_cash_ticker=by_cash_ticker)


def _upsert_security_instruments(
    conn: Connection,
    instrument: Table,
    *,
    isin_by_name: dict[str, str],
    holdings: Sequence[ParsedHoldingsFile],
) -> dict[str, str]:
    # Build payload keyed by ISIN. Pull name + currency from the first
    # holdings row whose name maps to that ISIN; fall back to the
    # raw name otherwise.
    name_for_isin: dict[str, str] = {n: i for n, i in {**isin_by_name}.items()}
    isin_to_name = {isin: name for name, isin in name_for_isin.items()}
    isin_to_currency: dict[str, str] = {}
    for hf in holdings:
        for h in hf.holdings:
            isin = isin_by_name.get(h.name)
            if isin is None:
                continue
            isin_to_currency.setdefault(isin, h.currency)

    payload = [
        {
            "isin": isin,
            "name": isin_to_name[isin],
            "kind": "security",
            "currency": isin_to_currency.get(isin, "DKK"),
        }
        for isin in sorted(isin_to_name)
    ]
    if not payload:
        return {}

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
    # ``isin`` column is CHAR(12); strip just in case.
    return {(r.isin or "").strip(): str(r.id) for r in rows}


def _upsert_cash_instruments(
    conn: Connection,
    instrument: Table,
    cash_balances: Sequence[ParsedCashBalance],
) -> dict[str, str]:
    """One ``CASH:<CCY>`` synthetic instrument per distinct currency.

    The schema has no unique index on ``(kind, ticker)``, so we
    SELECT first and INSERT the missing ones. This is fine in
    practice — the universe of currencies is tiny.
    """

    out: dict[str, str] = {}
    currencies = sorted({c.currency for c in cash_balances})
    for ccy in currencies:
        ticker = f"{CASH_TICKER_PREFIX}{ccy}"
        existing = conn.execute(
            select(instrument.c.id)
            .where((instrument.c.kind == CASH_INSTRUMENT_KIND) & (instrument.c.ticker == ticker))
            .limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            out[ticker] = str(existing)
            continue
        new_id = conn.execute(
            instrument.insert()
            .values(
                kind=CASH_INSTRUMENT_KIND,
                ticker=ticker,
                name=f"Cash ({ccy})",
                currency=ccy,
                isin=None,
            )
            .returning(instrument.c.id)
        ).scalar_one()
        out[ticker] = str(new_id)
    return out


# --------------------------------------------------------------------------- #
# transaction
# --------------------------------------------------------------------------- #


def _upsert_transactions(
    conn: Connection,
    transaction: Table,
    *,
    transactions: Sequence[ParsedTransaction],
    account_ids: dict[str, str],
    instrument_ids_by_isin: dict[str, str],
) -> int:
    payload: list[dict[str, object]] = []
    for t in transactions:
        account_id = account_ids[t.account_number]
        instrument_id: str | None = None
        if t.isin and t.isin in instrument_ids_by_isin:
            instrument_id = instrument_ids_by_isin[t.isin]
        ts = _to_utc_datetime(t.bookkeeping_date)

        counterparty: str | None = None
        if t.canonical_kind == TXN_KIND_INTERNAL_TRANSFER and t.counter_account:
            counterparty = f"nordnet:{t.counter_account}"

        payload.append(
            {
                "account_id": account_id,
                "instrument_id": instrument_id,
                "ts": ts,
                "value_date": t.value_date,
                "kind": t.canonical_kind,
                "quantity": t.quantity,
                "price": t.price,
                "amount": t.amount,
                "fee": t.fees if t.fees is not None else Decimal("0"),
                "tax": Decimal("0"),
                "fx_rate": t.fx_rate,
                "counterparty": counterparty,
                "description": t.text,
                "external_id": t.nordnet_id,
            }
        )

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


# --------------------------------------------------------------------------- #
# holding_snapshot
# --------------------------------------------------------------------------- #


def _upsert_holding_snapshots(
    conn: Connection,
    holding_snapshot: Table,
    *,
    holdings: Sequence[ParsedHoldingsFile],
    cash_balances: Sequence[ParsedCashBalance],
    account_ids: dict[str, str],
    instrument_ids_by_isin: dict[str, str],
    instrument_ids_by_cash_ticker: dict[str, str],
    isin_by_name: dict[str, str],
) -> int:
    payload: list[dict[str, object]] = []

    for hf in holdings:
        account_id = account_ids[hf.account_number]
        for h in hf.holdings:
            isin = isin_by_name.get(h.name)
            if isin is None or isin not in instrument_ids_by_isin:
                # No transaction history for this name yet → can't
                # reliably tie to an instrument row. Skip rather
                # than minting a name-only instrument.
                log.warning(
                    "skipping holding without ISIN mapping: account=%s name=%s",
                    hf.account_number,
                    h.name,
                )
                continue
            payload.append(
                _holding_payload(
                    account_id=account_id,
                    instrument_id=instrument_ids_by_isin[isin],
                    as_of=hf.as_of,
                    quantity=h.quantity,
                    price=h.last_price,
                    market_value=h.market_value_dkk,
                    cost_basis=_cost_basis(h),
                )
            )

    for c in cash_balances:
        ticker = f"{CASH_TICKER_PREFIX}{c.currency}"
        instrument_id = instrument_ids_by_cash_ticker[ticker]
        account_id = account_ids[c.account_number]
        payload.append(
            _holding_payload(
                account_id=account_id,
                instrument_id=instrument_id,
                as_of=c.as_of,
                quantity=c.saldo,
                price=Decimal("1"),
                market_value=c.saldo,
                cost_basis=c.saldo,
            )
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


def _cost_basis(h: ParsedHolding) -> Decimal | None:
    if h.avg_cost is None:
        return None
    return (h.avg_cost * h.quantity).quantize(Decimal("0.0001"))


def _holding_payload(
    *,
    account_id: str,
    instrument_id: str,
    as_of: object,
    quantity: Decimal,
    price: Decimal | None,
    market_value: Decimal | None,
    cost_basis: Decimal | None,
) -> dict[str, object]:
    return {
        "account_id": account_id,
        "instrument_id": instrument_id,
        "as_of": as_of,
        "quantity": quantity,
        "price": price,
        "market_value": market_value,
        "cost_basis": cost_basis,
    }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _to_utc_datetime(d: object) -> datetime:
    """Coerce a ``date`` to a timezone-aware UTC ``datetime`` for ``transaction.ts``.

    Nordnet exports day-precision booking dates; we anchor those at
    midnight UTC to give downstream marts a stable timestamp.
    """

    if not isinstance(d, date):
        raise TypeError(f"expected date, got {type(d).__name__}")
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "CASH_INSTRUMENT_KIND",
    "CASH_TICKER_PREFIX",
    "PROVIDER",
    "LoadResult",
    "UnknownAccountError",
    "load_files",
    "load_records",
]
