"""add isolated chat oauth storage

Revision ID: 0f3d2c1f4a9b
Revises: cb332a4e91df
Create Date: 2026-10-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0f3d2c1f4a9b"
down_revision: str | None = "cb332a4e91df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SERVICE_ROLE = "penge_chat_oauth"


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{SERVICE_ROLE}') THEN
                CREATE ROLE {SERVICE_ROLE}
                  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
              END IF;
            END
            $$;
            """
        )
    )

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

    op.execute(sa.text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {SERVICE_ROLE}"))
    op.execute(sa.text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {SERVICE_ROLE}"))
    op.execute(sa.text(f"GRANT USAGE ON SCHEMA public TO {SERVICE_ROLE}"))
    op.execute(
        sa.text(
            f"""
            GRANT SELECT, INSERT, UPDATE, DELETE
              ON chat_oauth_link, chat_oauth_state
              TO {SERVICE_ROLE}
            """
        )
    )
    op.execute(sa.text(f"GRANT INSERT ON chat_audit_event TO {SERVICE_ROLE}"))
    op.execute(
        sa.text(f"GRANT USAGE, SELECT ON SEQUENCE chat_audit_event_id_seq TO {SERVICE_ROLE}")
    )


def downgrade() -> None:
    op.execute(sa.text(f"REVOKE ALL PRIVILEGES ON chat_audit_event FROM {SERVICE_ROLE}"))
    op.execute(sa.text(f"REVOKE ALL PRIVILEGES ON chat_oauth_state FROM {SERVICE_ROLE}"))
    op.execute(sa.text(f"REVOKE ALL PRIVILEGES ON chat_oauth_link FROM {SERVICE_ROLE}"))
    op.execute(
        sa.text(f"REVOKE ALL PRIVILEGES ON SEQUENCE chat_audit_event_id_seq FROM {SERVICE_ROLE}")
    )
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
    op.execute(sa.text(f"REVOKE USAGE ON SCHEMA public FROM {SERVICE_ROLE}"))
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{SERVICE_ROLE}') THEN
                DROP ROLE {SERVICE_ROLE};
              END IF;
            END
            $$;
            """
        )
    )
