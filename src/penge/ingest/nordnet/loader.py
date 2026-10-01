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
    parse_holdings_file,
    parse_transactions,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine

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

    cash_balances = derive_cash_balances(transactions)

    meta = MetaData()
    tables = _reflect_tables(engine, meta)

    with engine.begin() as conn:
        _check_empty_snapshots_have_prior_securities(conn, tables, holdings)
        names_by_account = _holding_instrument_maps(
            conn, tables, transactions=transactions, holdings=holdings
        )
        referenced = {t.account_number for t in transactions} | {h.account_number for h in holdings}
        active_config = accounts_config.model_copy(
            update={
                "accounts": tuple(a for a in accounts_config.accounts if a.number in referenced)
            }
        )
        entity_ids = _upsert_entities(conn, tables["entity"], active_config)
        account_ids = _upsert_accounts(conn, tables["account"], active_config, entity_ids)
        instrument_names: dict[str, str] = {}
        for txn in transactions:
            if txn.instrument_name and txn.isin:
                instrument_names[txn.isin] = txn.instrument_name
        for account_map in names_by_account.values():
            for name, isin in account_map.items():
                instrument_names.setdefault(isin, name)
        instrument_ids = _upsert_instruments(
            conn,
            tables["instrument"],
            names_by_isin=instrument_names,
            transactions=transactions,
            holdings=holdings,
            cash_balances=cash_balances,
            names_by_account=names_by_account,
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
            tables["instrument"],
            holdings=holdings,
            cash_balances=cash_balances,
            account_ids=account_ids,
            instrument_ids_by_isin=instrument_ids.by_isin,
            instrument_ids_by_cash_ticker=instrument_ids.by_cash_ticker,
            names_by_account=names_by_account,
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


def _check_empty_snapshots_have_prior_securities(
    conn: Connection,
    tables: dict[str, Table],
    holdings: Sequence[ParsedHoldingsFile],
) -> None:
    """Do not create an account from a header-only file with no position history."""
    account = tables["account"]
    snapshot = tables["holding_snapshot"]
    instrument = tables["instrument"]
    for holding_file in holdings:
        if holding_file.holdings:
            continue
        known_security = (
            select(snapshot.c.instrument_id)
            .select_from(
                snapshot.join(account, snapshot.c.account_id == account.c.id).join(
                    instrument, snapshot.c.instrument_id == instrument.c.id
                )
            )
            .where(
                account.c.provider == PROVIDER,
                account.c.external_id == holding_file.account_number,
                snapshot.c.as_of <= holding_file.as_of,
                instrument.c.kind == "security",
                instrument.c.isin.is_not(None),
            )
            .limit(1)
        )
        if conn.execute(known_security).scalar_one_or_none() is None:
            raise ValueError(
                "empty Nordnet holdings export requires a prior mapped security "
                "snapshot for this account on or before its date"
            )


def _holding_instrument_maps(
    conn: Connection,
    tables: dict[str, Table],
    *,
    transactions: Sequence[ParsedTransaction],
    holdings: Sequence[ParsedHoldingsFile],
) -> dict[str, dict[str, str]]:
    """Resolve holdings names from same-account trades, snapshots, then this upload."""
    account = tables["account"]
    instrument = tables["instrument"]
    result: dict[str, dict[str, str]] = {}
    seen_snapshots: set[tuple[str, date]] = set()
    for hf in holdings:
        snapshot_key = (hf.account_number, hf.as_of)
        if snapshot_key in seen_snapshots:
            raise ValueError("duplicate Nordnet holdings account/date in one load")
        seen_snapshots.add(snapshot_key)
        names = {h.name for h in hf.holdings}
        mapping: dict[str, str] = {}
        if names:
            for source in ("transaction", "holding_snapshot"):
                records = tables[source]
                stmt = (
                    select(instrument.c.name, instrument.c.isin)
                    .select_from(
                        records.join(account, records.c.account_id == account.c.id).join(
                            instrument, records.c.instrument_id == instrument.c.id
                        )
                    )
                    .where(
                        account.c.provider == PROVIDER,
                        account.c.external_id == hf.account_number,
                        instrument.c.name.in_(names),
                        instrument.c.isin.is_not(None),
                    )
                    .distinct()
                )
                for name, isin in conn.execute(stmt):
                    current = mapping.get(name)
                    if current is not None and current != isin.strip():
                        raise ValueError("ambiguous Nordnet holding instrument in account history")
                    mapping[name] = isin.strip()
        for txn in transactions:
            if txn.account_number != hf.account_number or not txn.instrument_name or not txn.isin:
                continue
            current = mapping.get(txn.instrument_name)
            if current is not None and current != txn.isin:
                raise ValueError("conflicting Nordnet holding instrument in account history")
            mapping[txn.instrument_name] = txn.isin
        if names - mapping.keys():
            raise ValueError("Nordnet holding has no ISIN mapping in this account's history")
        resolved = [mapping[h.name] for h in hf.holdings]
        if len(resolved) != len(set(resolved)):
            raise ValueError("Nordnet holdings snapshot contains duplicate instruments")
        result[hf.account_number] = mapping
    return result


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
    names_by_isin: dict[str, str],
    transactions: Sequence[ParsedTransaction],
    holdings: Sequence[ParsedHoldingsFile],
    cash_balances: Sequence[ParsedCashBalance],
    names_by_account: dict[str, dict[str, str]],
) -> _InstrumentIds:
    by_isin = _upsert_security_instruments(
        conn,
        instrument,
        names_by_isin=names_by_isin,
        holdings=holdings,
        names_by_account=names_by_account,
        update_existing=bool(transactions),
    )
    by_cash_ticker = _upsert_cash_instruments(conn, instrument, cash_balances)
    return _InstrumentIds(by_isin=by_isin, by_cash_ticker=by_cash_ticker)


def _upsert_security_instruments(
    conn: Connection,
    instrument: Table,
    *,
    names_by_isin: dict[str, str],
    holdings: Sequence[ParsedHoldingsFile],
    names_by_account: dict[str, dict[str, str]],
    update_existing: bool,
) -> dict[str, str]:
    # Build payload keyed by ISIN. Pull name + currency from the first
    # holdings row whose name maps to that ISIN; fall back to the
    # raw name otherwise.
    isin_to_currency: dict[str, str] = {}
    for hf in holdings:
        for h in hf.holdings:
            isin = names_by_account[hf.account_number][h.name]
            isin_to_currency.setdefault(isin, h.currency)

    payload = [
        {
            "isin": isin,
            "name": names_by_isin[isin],
            "kind": "security",
            "currency": isin_to_currency.get(isin, "DKK"),
        }
        for isin in sorted(names_by_isin)
    ]
    if not payload:
        return {}

    existing: dict[str, str] = {}
    if not update_existing:
        existing = {
            isin.strip(): str(instrument_id)
            for instrument_id, isin in conn.execute(
                select(instrument.c.id, instrument.c.isin).where(
                    instrument.c.isin.in_(names_by_isin)
                )
            )
        }
        payload = [record for record in payload if record["isin"] not in existing]
        if not payload:
            return existing

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
    return {**existing, **{(r.isin or "").strip(): str(r.id) for r in rows}}


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
    instrument: Table,
    *,
    holdings: Sequence[ParsedHoldingsFile],
    cash_balances: Sequence[ParsedCashBalance],
    account_ids: dict[str, str],
    instrument_ids_by_isin: dict[str, str],
    instrument_ids_by_cash_ticker: dict[str, str],
    names_by_account: dict[str, dict[str, str]],
) -> int:
    written = 0
    for hf in sorted(holdings, key=lambda item: item.as_of):
        account_id = account_ids[hf.account_number]
        payload: list[dict[str, object]] = []
        for h in hf.holdings:
            isin = names_by_account[hf.account_number][h.name]
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
        present_ids = {entry["instrument_id"] for entry in payload}
        snapshot = holding_snapshot
        previous = (
            select(snapshot.c.instrument_id, snapshot.c.quantity, snapshot.c.market_value)
            .join(instrument, snapshot.c.instrument_id == instrument.c.id)
            .where(
                snapshot.c.account_id == account_id,
                snapshot.c.as_of <= hf.as_of,
                instrument.c.kind == "security",
            )
            .distinct(snapshot.c.instrument_id)
            .order_by(snapshot.c.instrument_id, snapshot.c.as_of.desc())
        )
        for instrument_id, quantity, market_value in conn.execute(previous):
            if str(instrument_id) in present_ids:
                continue
            if quantity == 0 and (market_value is None or market_value == 0):
                continue
            payload.append(
                _holding_payload(
                    account_id=account_id,
                    instrument_id=str(instrument_id),
                    as_of=hf.as_of,
                    quantity=Decimal("0"),
                    price=None,
                    market_value=Decimal("0"),
                    cost_basis=Decimal("0"),
                )
            )
        written += _write_snapshots(conn, holding_snapshot, payload)

    payload = []
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

    return written + _write_snapshots(conn, holding_snapshot, payload)


def _write_snapshots(
    conn: Connection,
    holding_snapshot: Table,
    payload: list[dict[str, object]],
) -> int:
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
