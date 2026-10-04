"""create chat oauth storage

Revision ID: chat0001
Revises:
Create Date: 2026-10-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "chat0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create only application-owned tables in the dedicated chat database."""
    op.create_table(
        "chat_oauth_link",
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("github_user_id", sa.BigInteger(), nullable=False),
        sa.Column("github_login", sa.String(length=128), nullable=False),
        sa.Column("token_envelope", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("actor_id", name="pk_chat_oauth_link"),
        sa.UniqueConstraint("github_user_id", name="uq_chat_oauth_link__github_user_id"),
    )
    op.create_index(
        "ix_chat_oauth_link__github_login",
        "chat_oauth_link",
        ["github_login"],
        unique=False,
    )
    op.create_table(
        "chat_oauth_state",
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("state_envelope", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("state_hash", name="pk_chat_oauth_state"),
        sa.UniqueConstraint("actor_id", name="uq_chat_oauth_state__actor_id"),
    )
    op.create_index(
        "ix_chat_oauth_state__actor_id_expires_at",
        "chat_oauth_state",
        ["actor_id", "expires_at"],
        unique=False,
    )
    op.create_table(
        "chat_audit_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("argument_keys", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_audit_event"),
        sa.CheckConstraint(
            "status IN ('started', 'completed', 'cancelled', 'timeout', 'error', 'denied')",
            name="ck_chat_audit_event__status",
        ),
    )
    op.create_index(
        "ix_chat_audit_event__actor_id_created_at",
        "chat_audit_event",
        ["actor_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_chat_audit_event__session_id",
        "chat_audit_event",
        ["session_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop only application-owned tables; deployment-owned roles remain."""
    op.drop_index("ix_chat_audit_event__session_id", table_name="chat_audit_event")
    op.drop_index("ix_chat_audit_event__actor_id_created_at", table_name="chat_audit_event")
    op.drop_table("chat_audit_event")
    op.drop_index(
        "ix_chat_oauth_state__actor_id_expires_at",
        table_name="chat_oauth_state",
    )
    op.drop_table("chat_oauth_state")
    op.drop_index("ix_chat_oauth_link__github_login", table_name="chat_oauth_link")
    op.drop_table("chat_oauth_link")
