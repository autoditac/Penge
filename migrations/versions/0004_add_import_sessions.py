"""add import_session and import_row staging tables

Staged import sessions (issue #207, ADR-0037): an uploaded statement
is parsed into ``import_row`` records hanging off one
``import_session``; nothing touches the raw tables until the session
is committed through the loaders.

``import_session`` tracks one uploaded file (source, original
filename, content hash, stored path, lifecycle status, commit
parameters) and ``import_row`` stores each parsed record as JSONB
together with validation status, issues, and row-level review state.

Revision ID: 0004_add_import_sessions
Revises: 0003_add_instrument_dk_tax
Create Date: 2026-06-13 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_add_import_sessions"
down_revision: str | None = "0003_add_instrument_dk_tax"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SESSION_STATUS_VALUES = ("staged", "committed", "discarded", "expired")
_ROW_STATUS_VALUES = ("ok", "warning", "error")

_SESSION_STATUS_CK = "ck_import_session__status"
_ROW_STATUS_CK = "ck_import_row__status"


def _uuid_pk() -> sa.Column[object]:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _ts(name: str, *, nullable: bool = True, default_now: bool = False) -> sa.Column[object]:
    kwargs: dict[str, object] = {"nullable": nullable}
    if default_now:
        kwargs["server_default"] = sa.text("now()")
    return sa.Column(name, sa.DateTime(timezone=True), **kwargs)


def upgrade() -> None:
    op.create_table(
        "import_session",
        _uuid_pk(),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("original_filename", sa.Text, nullable=False),
        sa.Column("content_sha256", sa.CHAR(64), nullable=False),
        sa.Column("stored_path", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'staged'")),
        sa.Column(
            "params",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error", sa.Text, nullable=True),
        _ts("created_at", nullable=False, default_now=True),
        _ts("updated_at", nullable=False, default_now=True),
        _ts("expires_at", nullable=False),
        _ts("committed_at", nullable=True),
    )
    op.create_check_constraint(
        _SESSION_STATUS_CK,
        "import_session",
        sa.text("status in ({})".format(", ".join(f"'{v}'" for v in _SESSION_STATUS_VALUES))),
    )
    op.create_index(
        "ix_import_session__status_expires_at",
        "import_session",
        ["status", "expires_at"],
    )

    op.create_table(
        "import_row",
        _uuid_pk(),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "import_session.id",
                name="fk_import_row__session_id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("row_index", sa.Integer, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'ok'")),
        sa.Column(
            "issues",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("edited", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("excluded", sa.Boolean, nullable=False, server_default=sa.text("false")),
        _ts("created_at", nullable=False, default_now=True),
        _ts("updated_at", nullable=False, default_now=True),
        sa.UniqueConstraint(
            "session_id",
            "row_index",
            name="ux_import_row__session_id_row_index",
        ),
    )
    op.create_check_constraint(
        _ROW_STATUS_CK,
        "import_row",
        sa.text("status in ({})".format(", ".join(f"'{v}'" for v in _ROW_STATUS_VALUES))),
    )
    op.create_index("ix_import_row__session_id", "import_row", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_import_row__session_id", table_name="import_row")
    op.drop_constraint(_ROW_STATUS_CK, "import_row", type_="check")
    op.drop_table("import_row")

    op.drop_index("ix_import_session__status_expires_at", table_name="import_session")
    op.drop_constraint(_SESSION_STATUS_CK, "import_session", type_="check")
    op.drop_table("import_session")
