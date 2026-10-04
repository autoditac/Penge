"""add chat oauth tables

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


def upgrade() -> None:
    op.create_table(
        "chat_oauth_link",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("google_subject", sa.String(length=256), nullable=False),
        sa.Column("github_login", sa.String(length=128), nullable=False),
        sa.Column("github_app_installation_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("actor_id", name="uq_chat_oauth_link__actor_id"),
        sa.UniqueConstraint("google_subject", name="uq_chat_oauth_link__google_subject"),
    )

    op.create_table(
        "chat_oauth_state",
        sa.Column("state", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("redirect_uri", sa.String(length=256), nullable=False),
        sa.Column("code_verifier", sa.String(length=256), nullable=False),
        sa.Column("code_challenge", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("state"),
    )

    op.create_table(
        "chat_oauth_nonce",
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("nonce"),
    )


def downgrade() -> None:
    op.drop_table("chat_oauth_nonce")
    op.drop_table("chat_oauth_state")
    op.drop_table("chat_oauth_link")
