"""add AI suggestion audit columns to import_row

AI review layer for the import wizard (issue #210, ADR-0038):
accepted mapping values (category / counterparty / asset_class) are
stored per staged row together with their provenance — which tool
suggested them and when the user accepted.

``mappings`` holds the accepted values keyed by field; ``suggested_by``
names the MCP tool when the values came from an accepted AI
suggestion (NULL for manual mappings); ``accepted_at`` records the
acceptance time (NULL until accepted).

Revision ID: 0005_add_import_row_suggestions
Revises: 0004_add_import_sessions
Create Date: 2026-06-14 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_add_import_row_suggestions"
down_revision: str | None = "0004_add_import_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "import_row",
        sa.Column(
            "mappings",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("import_row", sa.Column("suggested_by", sa.Text, nullable=True))
    op.add_column(
        "import_row",
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("import_row", "accepted_at")
    op.drop_column("import_row", "suggested_by")
    op.drop_column("import_row", "mappings")
