"""add account.dk_tax_treatment

Adds an optional ``dk_tax_treatment`` column on ``account`` so connectors
can tag accounts with their Danish tax regime (e.g. Aktiesparekonto on
Lunar). The column is nullable because most accounts do not carry a
DK-specific tax treatment, and is constrained to a small set of known
values so callers cannot drift.

Used by:

- :mod:`penge.ingest.lunar` (issue #16) — tags Aktiesparekonto
  subaccounts with ``aktiesparekonto``.

Revision ID: 0002_add_account_dk_tax
Revises: 0001_initial_schema
Create Date: 2026-05-08 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_account_dk_tax"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Allowed values. Extend in a follow-up migration when new DK regimes
# are introduced (e.g. ``pal``, ``virksomhedsordning``).
_ALLOWED = ("aktiesparekonto",)
_CONSTRAINT_NAME = "ck_account__dk_tax_treatment"


def upgrade() -> None:
    op.add_column(
        "account",
        sa.Column("dk_tax_treatment", sa.Text, nullable=True),
    )
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "account",
        sa.text(
            "dk_tax_treatment IS NULL OR dk_tax_treatment IN ("
            + ", ".join(f"'{v}'" for v in _ALLOWED)
            + ")"
        ),
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, "account", type_="check")
    op.drop_column("account", "dk_tax_treatment")
