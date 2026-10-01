"""Keep per-account owner and kind corrections across bank syncs.

Revision ID: 0007_account_metadata_overrides
Revises: 0006_add_bank_connection
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_account_metadata_overrides"
down_revision: str | None = "0006_add_bank_connection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("account", sa.Column("entity_override_id", postgresql.UUID(as_uuid=True)))
    op.add_column("account", sa.Column("kind_override", sa.Text))
    op.create_foreign_key(
        "fk_account__entity_override_id",
        "account",
        "entity",
        ["entity_override_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_account__kind_override",
        "account",
        "kind_override is null or kind_override in ('checking', 'savings')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_account__kind_override", "account", type_="check")
    op.drop_constraint("fk_account__entity_override_id", "account", type_="foreignkey")
    op.drop_column("account", "kind_override")
    op.drop_column("account", "entity_override_id")
