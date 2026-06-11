"""Persistence for import sessions and their staged rows.

SQLAlchemy Core against the two staging tables from migration
``0004_add_import_sessions``. The table objects are declared
statically (the migration is the source of truth for DDL); every
function takes the write engine from :mod:`penge.api.imports.engine`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.engine import Engine, Row

SESSION_STATUS_STAGED = "staged"
SESSION_STATUS_COMMITTED = "committed"
SESSION_STATUS_DISCARDED = "discarded"
SESSION_STATUS_EXPIRED = "expired"

ROW_STATUS_OK = "ok"
ROW_STATUS_WARNING = "warning"
ROW_STATUS_ERROR = "error"

_metadata = sa.MetaData()

import_session_table = sa.Table(
    "import_session",
    _metadata,
    sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    ),
    sa.Column("source", sa.Text, nullable=False),
    sa.Column("original_filename", sa.Text, nullable=False),
    sa.Column("content_sha256", sa.CHAR(64), nullable=False),
    sa.Column("stored_path", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("params", postgresql.JSONB, nullable=False),
    sa.Column("error", sa.Text, nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
)

import_row_table = sa.Table(
    "import_row",
    _metadata,
    sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    ),
    sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("row_index", sa.Integer, nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("payload", postgresql.JSONB, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("issues", postgresql.JSONB, nullable=False),
    sa.Column("edited", sa.Boolean, nullable=False),
    sa.Column("excluded", sa.Boolean, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)


@dataclass(frozen=True, slots=True)
class StagedRow:
    """One parsed record awaiting persistence (pre-insert shape)."""

    row_index: int
    kind: str
    payload: dict[str, object]
    status: str
    issues: list[dict[str, str]]


@dataclass(frozen=True, slots=True)
class RowRecord:
    """One staged row as stored."""

    id: uuid.UUID
    session_id: uuid.UUID
    row_index: int
    kind: str
    payload: dict[str, object]
    status: str
    issues: list[dict[str, str]]
    edited: bool
    excluded: bool


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """One import session as stored."""

    id: uuid.UUID
    source: str
    original_filename: str
    content_sha256: str
    stored_path: str
    status: str
    params: dict[str, object]
    error: str | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    committed_at: datetime | None


def _session_from_row(row: Row[tuple[object, ...]]) -> SessionRecord:
    m = row._mapping
    return SessionRecord(
        id=m["id"],
        source=m["source"],
        original_filename=m["original_filename"],
        content_sha256=m["content_sha256"],
        stored_path=m["stored_path"],
        status=m["status"],
        params=m["params"],
        error=m["error"],
        created_at=m["created_at"],
        updated_at=m["updated_at"],
        expires_at=m["expires_at"],
        committed_at=m["committed_at"],
    )


def _row_from_row(row: Row[tuple[object, ...]]) -> RowRecord:
    m = row._mapping
    return RowRecord(
        id=m["id"],
        session_id=m["session_id"],
        row_index=m["row_index"],
        kind=m["kind"],
        payload=m["payload"],
        status=m["status"],
        issues=m["issues"],
        edited=m["edited"],
        excluded=m["excluded"],
    )


def create_session(
    engine: Engine,
    *,
    source: str,
    original_filename: str,
    content_sha256: str,
    stored_path: str,
    params: dict[str, object],
    ttl_days: int,
    rows: Sequence[StagedRow],
) -> SessionRecord:
    """Insert one session plus all its staged rows in one transaction."""
    expires_at = datetime.now(UTC) + timedelta(days=ttl_days)
    with engine.begin() as conn:
        inserted = conn.execute(
            sa.insert(import_session_table)
            .values(
                source=source,
                original_filename=original_filename,
                content_sha256=content_sha256,
                stored_path=stored_path,
                status=SESSION_STATUS_STAGED,
                params=params,
                expires_at=expires_at,
            )
            .returning(*import_session_table.c)
        ).one()
        session = _session_from_row(inserted)
        if rows:
            conn.execute(
                sa.insert(import_row_table),
                [
                    {
                        "session_id": session.id,
                        "row_index": r.row_index,
                        "kind": r.kind,
                        "payload": r.payload,
                        "status": r.status,
                        "issues": r.issues,
                        "edited": False,
                        "excluded": False,
                    }
                    for r in rows
                ],
            )
    return session


def get_session(engine: Engine, session_id: uuid.UUID) -> SessionRecord | None:
    """Return one session, or ``None`` when the id is unknown."""
    stmt = sa.select(import_session_table).where(import_session_table.c.id == session_id)
    with engine.connect() as conn:
        row = conn.execute(stmt).one_or_none()
    return None if row is None else _session_from_row(row)


def list_sessions(engine: Engine, *, limit: int, offset: int) -> tuple[list[SessionRecord], int]:
    """Return one page of sessions (newest first) plus the total count."""
    stmt = (
        sa.select(import_session_table)
        .order_by(import_session_table.c.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    count_stmt = sa.select(sa.func.count()).select_from(import_session_table)
    with engine.connect() as conn:
        rows = conn.execute(stmt).all()
        total = conn.execute(count_stmt).scalar_one()
    return [_session_from_row(r) for r in rows], int(total)


def expire_if_stale(engine: Engine, session: SessionRecord) -> SessionRecord:
    """Flip a staged session past its TTL to ``expired`` (lazy expiry)."""
    if session.status != SESSION_STATUS_STAGED:
        return session
    if session.expires_at > datetime.now(UTC):
        return session
    return set_session_status(engine, session.id, SESSION_STATUS_EXPIRED)


def set_session_status(
    engine: Engine,
    session_id: uuid.UUID,
    status: str,
    *,
    error: str | None = None,
    committed: bool = False,
) -> SessionRecord:
    """Update a session's lifecycle status and return the new record."""
    values: dict[str, object] = {"status": status, "updated_at": sa.func.now()}
    if error is not None:
        values["error"] = error
    if committed:
        values["committed_at"] = sa.func.now()
    stmt = (
        sa.update(import_session_table)
        .where(import_session_table.c.id == session_id)
        .values(**values)
        .returning(*import_session_table.c)
    )
    with engine.begin() as conn:
        row = conn.execute(stmt).one()
    return _session_from_row(row)


def get_rows(
    engine: Engine,
    session_id: uuid.UUID,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[RowRecord], int]:
    """Return one page of a session's rows plus the total count."""
    stmt = (
        sa.select(import_row_table)
        .where(import_row_table.c.session_id == session_id)
        .order_by(import_row_table.c.row_index)
        .offset(offset)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    count_stmt = (
        sa.select(sa.func.count())
        .select_from(import_row_table)
        .where(import_row_table.c.session_id == session_id)
    )
    with engine.connect() as conn:
        rows = conn.execute(stmt).all()
        total = conn.execute(count_stmt).scalar_one()
    return [_row_from_row(r) for r in rows], int(total)


def get_row(engine: Engine, session_id: uuid.UUID, row_id: uuid.UUID) -> RowRecord | None:
    """Return one row of one session, or ``None`` when not found."""
    stmt = sa.select(import_row_table).where(
        import_row_table.c.session_id == session_id,
        import_row_table.c.id == row_id,
    )
    with engine.connect() as conn:
        row = conn.execute(stmt).one_or_none()
    return None if row is None else _row_from_row(row)


def update_row(
    engine: Engine,
    row_id: uuid.UUID,
    *,
    payload: dict[str, object] | None = None,
    status: str | None = None,
    issues: list[dict[str, str]] | None = None,
    excluded: bool | None = None,
    edited: bool | None = None,
) -> RowRecord:
    """Persist a row correction and return the new record."""
    values: dict[str, object] = {"updated_at": sa.func.now()}
    if payload is not None:
        values["payload"] = payload
    if status is not None:
        values["status"] = status
    if issues is not None:
        values["issues"] = issues
    if excluded is not None:
        values["excluded"] = excluded
    if edited is not None:
        values["edited"] = edited
    stmt = (
        sa.update(import_row_table)
        .where(import_row_table.c.id == row_id)
        .values(**values)
        .returning(*import_row_table.c)
    )
    with engine.begin() as conn:
        row = conn.execute(stmt).one()
    return _row_from_row(row)


def existing_transaction_external_ids(
    engine: Engine,
    *,
    provider: str,
    account_external_id: str,
    candidate_ids: Sequence[str],
) -> set[str]:
    """Return which candidate external ids already exist for one account.

    Mirrors the loaders' upsert key
    (``ux_transaction__account_id_external_id``) so a staged row can be
    flagged as a duplicate of an already-loaded transaction.
    """
    if not candidate_ids:
        return set()
    stmt = sa.text(
        """
        select t.external_id
        from transaction as t
        inner join account as a on a.id = t.account_id
        where a.provider = :provider
          and a.external_id = :account_external_id
          and t.external_id = any(:candidate_ids)
        """
    ).bindparams(sa.bindparam("candidate_ids", type_=postgresql.ARRAY(sa.Text)))
    with engine.connect() as conn:
        rows = conn.execute(
            stmt,
            {
                "provider": provider,
                "account_external_id": account_external_id,
                "candidate_ids": list(candidate_ids),
            },
        ).all()
    return {str(r[0]) for r in rows}
