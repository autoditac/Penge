"""PFA → Postgres loader.

Given one or more parsed PFA Pensionsoversigt PDFs and an entity
(person) name, upsert everything (entity, account per scheme,
synthesised PFA-fund instruments, holding snapshots, contributions
and return / fee / PAL-skat transactions) into the operational
schema.

Idempotent — re-running with the same PDFs converges to the same
database state. Transactions get a synthesised ``external_id``
(see ``synthesize_external_id``) so re-loading the same statement
period does not duplicate rows.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import MetaData, Table, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from penge.ingest.pfa.constants import (
    INSTRUMENT_KIND_FUND,
    PFA_FUND_TICKER_PREFIX,
    PROVIDER,
    TXN_KIND_CONTRIBUTION,
    TXN_KIND_FEE,
    TXN_KIND_PAL_SKAT,
    TXN_KIND_RETURN,
)
from penge.ingest.pfa.models import (
    ParsedHolding,
    ParsedPensionsoversigt,
    ParsedScheme,
)
from penge.ingest.pfa.parser import parse_pensionsoversigt, synthesize_external_id

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine

log = logging.getLogger("penge.ingest.pfa.loader")

ACCOUNT_CURRENCY = "DKK"
ENTITY_KIND = "person"


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
    allow_ocr: bool = True,
) -> LoadResult:
    """Parse the given PFA PDFs and upsert everything into Postgres."""

    parsed = [parse_pensionsoversigt(p, allow_ocr=allow_ocr) for p in pdf_paths]
    return load_records(engine, statements=parsed, entity_name=entity_name)


def load_records(
    engine: Engine,
    *,
    statements: Sequence[ParsedPensionsoversigt],
    entity_name: str,
) -> LoadResult:
    """Upsert pre-parsed Pensionsoversigt records.

    All writes happen inside a single transaction; a failure rolls
    the whole load back, leaving the database unchanged.
    """

    if not statements:
        return LoadResult(0, 0, 0, 0, 0)

    md = MetaData()
    with engine.begin() as conn:
        entity = Table("entity", md, autoload_with=conn)
        account = Table("account", md, autoload_with=conn)
        instrument = Table("instrument", md, autoload_with=conn)
        transaction = Table("transaction", md, autoload_with=conn)
        holding_snapshot = Table("holding_snapshot", md, autoload_with=conn)

        entity_id = _get_or_create_entity(conn, entity, name=entity_name)

        accounts: set[str] = set()
        instruments = 0
        transactions_count = 0
        snapshots = 0

        for stmt in statements:
            for scheme in stmt.schemes:
                account_id = _get_or_create_account(
                    conn,
                    account,
                    entity_id=entity_id,
                    policy_number=stmt.policy_number,
                    scheme=scheme,
                )
                accounts.add(account_id)
                transactions_count += _upsert_scheme_transactions(
                    conn,
                    transaction,
                    account_id=account_id,
                    policy_number=stmt.policy_number,
                    scheme=scheme,
                    period_to=stmt.period_to or stmt.as_of,
                )
                if scheme.holdings:
                    n_inst, n_snap = _upsert_holdings(
                        conn,
                        instrument=instrument,
                        holding_snapshot=holding_snapshot,
                        account_id=account_id,
                        as_of=stmt.as_of,
                        holdings=scheme.holdings,
                    )
                    instruments += n_inst
                    snapshots += n_snap

    return LoadResult(
        entities=1,
        accounts=len(accounts),
        instruments=instruments,
        transactions=transactions_count,
        holding_snapshots=snapshots,
    )


# --- helpers: entity / account / instrument --------------------------------


def _get_or_create_entity(conn: Connection, entity: Table, *, name: str) -> str:
    existing = conn.execute(
        select(entity.c.id).where(entity.c.name == name, entity.c.kind == ENTITY_KIND).limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return str(existing)
    new_id = conn.execute(
        entity.insert().values(name=name, kind=ENTITY_KIND).returning(entity.c.id)
    ).scalar_one()
    return str(new_id)


def _account_external_id(policy_number: str, scheme: ParsedScheme) -> str:
    """Stable per-policy / per-scheme account identifier."""

    return f"{policy_number}:{scheme.scheme_kind}:{scheme.sub_policy_id}"


def _get_or_create_account(
    conn: Connection,
    account: Table,
    *,
    entity_id: str,
    policy_number: str,
    scheme: ParsedScheme,
) -> str:
    """Upsert one ``account`` row per (policy, scheme).

    ``account.kind`` carries the canonical Danish pension regime
    (e.g. ``ratepension``); the regime fully determines the SKAT
    treatment so we do *not* set ``dk_tax_treatment`` (PAL-skat
    applies to all PFA schemes implicitly).
    """

    external_id = _account_external_id(policy_number, scheme)
    name = f"PFA {scheme.scheme_kind.replace('_', ' ').title()} {policy_number}"
    stmt = pg_insert(account).values(
        entity_id=entity_id,
        provider=PROVIDER,
        external_id=external_id,
        name=name,
        kind=scheme.scheme_kind,
        currency=ACCOUNT_CURRENCY,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="ux_account__provider_external_id",
        set_={
            "entity_id": stmt.excluded.entity_id,
            "name": stmt.excluded.name,
            "kind": stmt.excluded.kind,
            "currency": stmt.excluded.currency,
            "updated_at": func.now(),
        },
    ).returning(account.c.id)
    return str(conn.execute(stmt).scalar_one())


_TICKER_SLUG_RE = re.compile(r"[^A-Z0-9]+")


def _fund_ticker(fund_name: str) -> str:
    """Slugify a PFA fund name into a stable, ASCII-only ticker.

    Examples::

        "PFA Plus AA"            -> "PFA:PFAPLUSAA"
        "PFA Globale Aktier"     -> "PFA:PFAGLOBALEAKTIER"
        "Hedge Lav Risiko"       -> "PFA:HEDGELAVRISIKO"
    """

    norm = (
        unicodedata.normalize("NFKD", fund_name).encode("ascii", "ignore").decode("ascii").upper()
    )
    slug = _TICKER_SLUG_RE.sub("", norm)
    if not slug:
        slug = "UNKNOWN"
    return f"{PFA_FUND_TICKER_PREFIX}{slug}"


def _get_or_create_fund_instrument(
    conn: Connection,
    instrument: Table,
    *,
    fund_name: str,
) -> tuple[str, bool]:
    """Upsert a synthesised instrument for a PFA fund.

    Returns ``(instrument_id, created)``. ``created`` lets the
    caller increment the ``LoadResult.instruments`` counter only
    when a new row was actually inserted.
    """

    ticker = _fund_ticker(fund_name)
    existing = conn.execute(
        select(instrument.c.id)
        .where(
            instrument.c.kind == INSTRUMENT_KIND_FUND,
            instrument.c.ticker == ticker,
        )
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return str(existing), False
    new_id = conn.execute(
        instrument.insert()
        .values(
            kind=INSTRUMENT_KIND_FUND,
            ticker=ticker,
            name=fund_name,
            currency=ACCOUNT_CURRENCY,
            isin=None,
        )
        .returning(instrument.c.id)
    ).scalar_one()
    return str(new_id), True


# --- helpers: holdings -----------------------------------------------------


def _upsert_holdings(
    conn: Connection,
    *,
    instrument: Table,
    holding_snapshot: Table,
    account_id: str,
    as_of: date,
    holdings: tuple[ParsedHolding, ...],
) -> tuple[int, int]:
    instruments_created = 0
    rows: list[dict[str, object]] = []
    for h in holdings:
        instrument_id, created = _get_or_create_fund_instrument(
            conn, instrument, fund_name=h.fund_name
        )
        if created:
            instruments_created += 1
        rows.append(
            {
                "account_id": account_id,
                "instrument_id": instrument_id,
                "as_of": as_of,
                "quantity": h.quantity if h.quantity is not None else Decimal("1"),
                "price": None,
                "market_value": h.market_value_dkk,
                "cost_basis": None,
            }
        )
    if not rows:
        return instruments_created, 0
    stmt = pg_insert(holding_snapshot).values(rows)
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
    return instruments_created, len(rows)


# --- helpers: transactions -------------------------------------------------


def _upsert_scheme_transactions(
    conn: Connection,
    transaction: Table,
    *,
    account_id: str,
    policy_number: str,
    scheme: ParsedScheme,
    period_to: date,
) -> int:
    """Post one transaction row per PFA financial-summary line.

    PFA does not break out individual transfer dates on the
    consumer statement; everything is dated on ``period_to`` (the
    end of the reported period).
    """

    rows: list[dict[str, object]] = []
    ts = datetime.combine(period_to, datetime.min.time(), tzinfo=UTC)

    for contribution in scheme.contributions:
        if contribution.amount_dkk == 0:
            continue
        rows.append(
            _txn_row(
                account_id=account_id,
                ts=ts,
                value_date=period_to,
                kind=TXN_KIND_CONTRIBUTION,
                amount=contribution.amount_dkk,
                description=f"Contribution ({contribution.source})",
                external_id=synthesize_external_id(
                    policy_number=policy_number,
                    scheme_kind=scheme.scheme_kind,
                    sub_policy_id=scheme.sub_policy_id,
                    txn_kind=TXN_KIND_CONTRIBUTION,
                    period_to=period_to,
                    detail=contribution.source,
                ),
            )
        )

    if scheme.return_dkk != 0:
        rows.append(
            _txn_row(
                account_id=account_id,
                ts=ts,
                value_date=period_to,
                kind=TXN_KIND_RETURN,
                amount=scheme.return_dkk,
                description="Investment return",
                external_id=synthesize_external_id(
                    policy_number=policy_number,
                    scheme_kind=scheme.scheme_kind,
                    sub_policy_id=scheme.sub_policy_id,
                    txn_kind=TXN_KIND_RETURN,
                    period_to=period_to,
                    detail="afkast",
                ),
            )
        )

    if scheme.fees_dkk != 0:
        # Fees are printed as a positive deduction on the statement;
        # post as a negative ``fee`` so the running balance reconciles.
        rows.append(
            _txn_row(
                account_id=account_id,
                ts=ts,
                value_date=period_to,
                kind=TXN_KIND_FEE,
                amount=-abs(scheme.fees_dkk),
                description="Fees (Omkostninger)",
                external_id=synthesize_external_id(
                    policy_number=policy_number,
                    scheme_kind=scheme.scheme_kind,
                    sub_policy_id=scheme.sub_policy_id,
                    txn_kind=TXN_KIND_FEE,
                    period_to=period_to,
                    detail="omkostninger",
                ),
            )
        )

    if scheme.pal_skat_dkk != 0:
        rows.append(
            _txn_row(
                account_id=account_id,
                ts=ts,
                value_date=period_to,
                kind=TXN_KIND_PAL_SKAT,
                amount=-abs(scheme.pal_skat_dkk),
                description="PAL-skat",
                external_id=synthesize_external_id(
                    policy_number=policy_number,
                    scheme_kind=scheme.scheme_kind,
                    sub_policy_id=scheme.sub_policy_id,
                    txn_kind=TXN_KIND_PAL_SKAT,
                    period_to=period_to,
                    detail="pal-skat",
                ),
            )
        )

    if not rows:
        return 0

    stmt = pg_insert(transaction).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="ux_transaction__account_id_external_id",
        set_={
            "ts": stmt.excluded.ts,
            "value_date": stmt.excluded.value_date,
            "kind": stmt.excluded.kind,
            "amount": stmt.excluded.amount,
            "description": stmt.excluded.description,
        },
    )
    conn.execute(stmt)
    return len(rows)


def _txn_row(
    *,
    account_id: str,
    ts: datetime,
    value_date: date,
    kind: str,
    amount: Decimal,
    description: str,
    external_id: str,
) -> dict[str, object]:
    """Build a transaction-row dict ready for ``pg_insert``."""

    return {
        "account_id": account_id,
        "instrument_id": None,
        "ts": ts,
        "value_date": value_date,
        "kind": kind,
        "quantity": None,
        "price": None,
        "amount": amount,
        "fee": Decimal("0"),
        "tax": Decimal("0"),
        "fx_rate": None,
        "counterparty": None,
        "description": description,
        "external_id": external_id,
    }
