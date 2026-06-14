"""add bank_connection table for Enable Banking sessions

In-app Enable Banking consent flow (issue #230, ADR-0040). A
``bank_connection`` row records one PSD2 consent: the ASPSP it targets,
the opaque ``state``/``authorization_id`` minted at link time, the
``session_id`` returned after the PSU completes SCA, the consent
expiry, a snapshot of the authorised accounts, and the outcome of the
most recent sync (status plus a sanitised error payload for debugging
failed imports).

Persisting the session is what lets a sync re-run without a fresh
consent: an Enable Banking session is valid for the consent window
(~180 days), so only an expired or revoked session forces re-consent.

Revision ID: 0006_add_bank_connection
Revises: 0005_add_import_row_suggestions
Create Date: 2026-06-14 22:45:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_add_bank_connection"
down_revision: str | None = "0005_add_import_row_suggestions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Consent lifecycle. ``linking`` = authorization started, awaiting the
# redirect ``code``; ``authorized`` = a usable session is stored;
# ``expired`` = the consent window elapsed (re-consent required);
# ``error`` = the last link/authorize/sync failed (see ``last_error``).
_STATUS_VALUES = ("linking", "authorized", "expired", "error")
_SYNC_STATUS_VALUES = ("ok", "error")

_STATUS_CK = "ck_bank_connection__status"
_SYNC_STATUS_CK = "ck_bank_connection__last_sync_status"


def upgrade() -> None:
    op.create_table(
        "bank_connection",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("aspsp_name", sa.Text, nullable=False),
        sa.Column("aspsp_country", sa.CHAR(2), nullable=False),
        sa.Column("entity_name", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'linking'")),
        sa.Column("state", sa.Text, nullable=True),
        sa.Column("authorization_id", sa.Text, nullable=True),
        sa.Column("session_id", sa.Text, nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "accounts",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.Text, nullable=True),
        sa.Column("last_error", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_check_constraint(
        _STATUS_CK,
        "bank_connection",
        sa.text("status in ({})".format(", ".join(f"'{v}'" for v in _STATUS_VALUES))),
    )
    op.create_check_constraint(
        _SYNC_STATUS_CK,
        "bank_connection",
        sa.text(
            "last_sync_status is null or last_sync_status in ({})".format(
                ", ".join(f"'{v}'" for v in _SYNC_STATUS_VALUES)
            )
        ),
    )
    # State is the CSRF nonce echoed back on the un-gated callback; it
    # must resolve to exactly one pending connection.
    op.create_index(
        "ux_bank_connection__state",
        "bank_connection",
        ["state"],
        unique=True,
        postgresql_where=sa.text("state is not null"),
    )
    op.create_index("ix_bank_connection__provider", "bank_connection", ["provider"])
    op.create_index("ix_bank_connection__status", "bank_connection", ["status"])


def downgrade() -> None:
    op.drop_index("ix_bank_connection__status", table_name="bank_connection")
    op.drop_index("ix_bank_connection__provider", table_name="bank_connection")
    op.drop_index("ux_bank_connection__state", table_name="bank_connection")
    op.drop_constraint(_SYNC_STATUS_CK, "bank_connection", type_="check")
    op.drop_constraint(_STATUS_CK, "bank_connection", type_="check")
    op.drop_table("bank_connection")
