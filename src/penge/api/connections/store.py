"""Persistence for bank connections (Enable Banking consents).

SQLAlchemy Core against the ``bank_connection`` table from migration
``0006_add_bank_connection``. The table is declared statically (the
migration is the source of truth for DDL). All writes use the
write-enabled engine from :mod:`penge.api.imports.engine`; the
read-only API engine (ADR-0035) is never used here.

Re-using a stored connection is what lets a sync run without a fresh
consent: an Enable Banking session is valid for the consent window
(~180 days), so only an expired/revoked session forces re-linking.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine, Row

STATUS_LINKING = "linking"
STATUS_AUTHORIZED = "authorized"
STATUS_EXPIRED = "expired"
STATUS_ERROR = "error"

SYNC_STATUS_OK = "ok"
SYNC_STATUS_ERROR = "error"

_metadata = sa.MetaData()

bank_connection_table = sa.Table(
    "bank_connection",
    _metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("provider", sa.Text, nullable=False),
    sa.Column("aspsp_name", sa.Text, nullable=False),
    sa.Column("aspsp_country", sa.CHAR(2), nullable=False),
    sa.Column("entity_name", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("state", sa.Text, nullable=True),
    sa.Column("authorization_id", sa.Text, nullable=True),
    sa.Column("session_id", sa.Text, nullable=True),
    sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
    sa.Column("accounts", postgresql.JSONB, nullable=False),
    sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("last_sync_status", sa.Text, nullable=True),
    sa.Column("last_error", postgresql.JSONB, nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)


@dataclass(frozen=True, slots=True)
class ConnectionRecord:
    """One ``bank_connection`` row as a typed Python object."""

    id: uuid.UUID
    provider: str
    aspsp_name: str
    aspsp_country: str
    entity_name: str
    status: str
    state: str | None
    authorization_id: str | None
    session_id: str | None
    valid_until: datetime | None
    accounts: list[dict[str, object]]
    last_sync_at: datetime | None
    last_sync_status: str | None
    last_error: dict[str, object] | None
    created_at: datetime
    updated_at: datetime


def _record(row: Row[tuple[object, ...]]) -> ConnectionRecord:
    m = row._mapping
    raw_accounts = m["accounts"]
    accounts = list(raw_accounts) if isinstance(raw_accounts, list) else []
    raw_error = m["last_error"]
    last_error = raw_error if isinstance(raw_error, dict) else None
    return ConnectionRecord(
        id=m["id"],
        provider=m["provider"],
        aspsp_name=m["aspsp_name"],
        aspsp_country=m["aspsp_country"],
        entity_name=m["entity_name"],
        status=m["status"],
        state=m["state"],
        authorization_id=m["authorization_id"],
        session_id=m["session_id"],
        valid_until=m["valid_until"],
        accounts=accounts,
        last_sync_at=m["last_sync_at"],
        last_sync_status=m["last_sync_status"],
        last_error=last_error,
        created_at=m["created_at"],
        updated_at=m["updated_at"],
    )


def create_linking(
    engine: Engine,
    *,
    provider: str,
    aspsp_name: str,
    aspsp_country: str,
    entity_name: str,
    state: str,
    authorization_id: str,
    valid_until: datetime,
) -> ConnectionRecord:
    """Insert a ``linking`` connection awaiting the redirect ``code``."""
    now = datetime.now(UTC)
    stmt = (
        sa.insert(bank_connection_table)
        .values(
            id=uuid.uuid4(),
            provider=provider,
            aspsp_name=aspsp_name,
            aspsp_country=aspsp_country,
            entity_name=entity_name,
            status=STATUS_LINKING,
            state=state,
            authorization_id=authorization_id,
            session_id=None,
            valid_until=valid_until,
            accounts=[],
            last_sync_at=None,
            last_sync_status=None,
            last_error=None,
            created_at=now,
            updated_at=now,
        )
        .returning(bank_connection_table)
    )
    with engine.begin() as conn:
        return _record(conn.execute(stmt).one())


def list_connections(engine: Engine) -> list[ConnectionRecord]:
    """Return all connections, newest first."""
    stmt = sa.select(bank_connection_table).order_by(bank_connection_table.c.created_at.desc())
    with engine.connect() as conn:
        return [_record(row) for row in conn.execute(stmt)]


def get_connection(engine: Engine, connection_id: uuid.UUID) -> ConnectionRecord | None:
    """Return one connection by id, or ``None``."""
    stmt = sa.select(bank_connection_table).where(bank_connection_table.c.id == connection_id)
    with engine.connect() as conn:
        row = conn.execute(stmt).one_or_none()
    return _record(row) if row is not None else None


def get_by_state(engine: Engine, state: str) -> ConnectionRecord | None:
    """Return the pending connection matching the CSRF ``state``."""
    stmt = sa.select(bank_connection_table).where(bank_connection_table.c.state == state)
    with engine.connect() as conn:
        row = conn.execute(stmt).one_or_none()
    return _record(row) if row is not None else None


def mark_authorized(
    engine: Engine,
    connection_id: uuid.UUID,
    *,
    session_id: str,
    valid_until: datetime,
    accounts: list[dict[str, object]],
) -> ConnectionRecord:
    """Store the session id + authorised accounts after SCA succeeds."""
    stmt = (
        sa.update(bank_connection_table)
        .where(bank_connection_table.c.id == connection_id)
        .values(
            status=STATUS_AUTHORIZED,
            session_id=session_id,
            valid_until=valid_until,
            accounts=accounts,
            state=None,
            last_error=None,
            updated_at=datetime.now(UTC),
        )
        .returning(bank_connection_table)
    )
    with engine.begin() as conn:
        return _record(conn.execute(stmt).one())


def record_sync_ok(
    engine: Engine,
    connection_id: uuid.UUID,
    *,
    accounts: list[dict[str, object]] | None = None,
) -> ConnectionRecord:
    """Record a successful sync; optionally refresh the account snapshot."""
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "status": STATUS_AUTHORIZED,
        "last_sync_at": now,
        "last_sync_status": SYNC_STATUS_OK,
        "last_error": None,
        "updated_at": now,
    }
    if accounts is not None:
        values["accounts"] = accounts
    stmt = (
        sa.update(bank_connection_table)
        .where(bank_connection_table.c.id == connection_id)
        .values(**values)
        .returning(bank_connection_table)
    )
    with engine.begin() as conn:
        return _record(conn.execute(stmt).one())


def record_error(
    engine: Engine,
    connection_id: uuid.UUID,
    *,
    error: dict[str, object],
    status: str = STATUS_ERROR,
    is_sync: bool = False,
) -> ConnectionRecord:
    """Record a sanitised error payload for debugging a failed step."""
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "status": status,
        "last_error": error,
        "updated_at": now,
    }
    if is_sync:
        values["last_sync_at"] = now
        values["last_sync_status"] = SYNC_STATUS_ERROR
    stmt = (
        sa.update(bank_connection_table)
        .where(bank_connection_table.c.id == connection_id)
        .values(**values)
        .returning(bank_connection_table)
    )
    with engine.begin() as conn:
        return _record(conn.execute(stmt).one())


__all__ = [
    "STATUS_AUTHORIZED",
    "STATUS_ERROR",
    "STATUS_EXPIRED",
    "STATUS_LINKING",
    "SYNC_STATUS_ERROR",
    "SYNC_STATUS_OK",
    "ConnectionRecord",
    "bank_connection_table",
    "create_linking",
    "get_by_state",
    "get_connection",
    "list_connections",
    "mark_authorized",
    "record_error",
    "record_sync_ok",
]
