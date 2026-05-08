"""add instrument DK tax columns + instrument_dk_abis_listing

Adds the per-instrument Danish tax classification needed by the tax
engine (issue #34) and an append-only audit table tracking each
ISIN/year combination observed on a Skat ABIS-list import.

Schema additions on ``instrument``:

- ``dk_tax_treatment`` (Text, nullable) — one of
  ``lagerbeskatning`` / ``realisation``.
- ``dk_tax_treatment_source`` (Text, nullable) — one of
  ``abis`` / ``manual``. Required iff ``dk_tax_treatment`` is set.

New table ``instrument_dk_abis_listing`` with columns
``(id, instrument_id, tax_year, listed, source_file, imported_at)``
and unique constraint ``ux_instrument_dk_abis_listing__instrument_id_tax_year``.

See ADR-0009 for the full rationale.

Revision ID: 0003_add_instrument_dk_tax
Revises: 0002_add_account_dk_tax
Create Date: 2026-05-08 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_add_instrument_dk_tax"
down_revision: str | None = "0002_add_account_dk_tax"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TREATMENT_VALUES = ("lagerbeskatning", "realisation")
_SOURCE_VALUES = ("abis", "manual")

_TREATMENT_CK = "ck_instrument__dk_tax_treatment"
_SOURCE_CK = "ck_instrument__dk_tax_treatment_source"
_PAIR_CK = "ck_instrument__dk_tax_treatment_pair"


def upgrade() -> None:
    op.add_column(
        "instrument",
        sa.Column("dk_tax_treatment", sa.Text, nullable=True),
    )
    op.add_column(
        "instrument",
        sa.Column("dk_tax_treatment_source", sa.Text, nullable=True),
    )
    op.create_check_constraint(
        _TREATMENT_CK,
        "instrument",
        sa.text(
            "dk_tax_treatment IS NULL OR dk_tax_treatment IN ("
            + ", ".join(f"'{v}'" for v in _TREATMENT_VALUES)
            + ")"
        ),
    )
    op.create_check_constraint(
        _SOURCE_CK,
        "instrument",
        sa.text(
            "dk_tax_treatment_source IS NULL OR dk_tax_treatment_source IN ("
            + ", ".join(f"'{v}'" for v in _SOURCE_VALUES)
            + ")"
        ),
    )
    # Both NULL or both NOT NULL — a treatment without a source is ambiguous.
    op.create_check_constraint(
        _PAIR_CK,
        "instrument",
        sa.text(
            "(dk_tax_treatment IS NULL AND dk_tax_treatment_source IS NULL) "
            "OR (dk_tax_treatment IS NOT NULL AND dk_tax_treatment_source IS NOT NULL)"
        ),
    )

    op.create_table(
        "instrument_dk_abis_listing",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tax_year", sa.SmallInteger, nullable=False),
        sa.Column("listed", sa.Boolean, nullable=False),
        sa.Column("source_file", sa.Text, nullable=True),
        sa.Column(
            "imported_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instrument.id"],
            name="fk_instrument_dk_abis_listing__instrument_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "instrument_id",
            "tax_year",
            name="ux_instrument_dk_abis_listing__instrument_id_tax_year",
        ),
    )
    op.create_index(
        "ix_instrument_dk_abis_listing__tax_year",
        "instrument_dk_abis_listing",
        ["tax_year"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_instrument_dk_abis_listing__tax_year",
        table_name="instrument_dk_abis_listing",
    )
    op.drop_table("instrument_dk_abis_listing")
    op.drop_constraint(_PAIR_CK, "instrument", type_="check")
    op.drop_constraint(_SOURCE_CK, "instrument", type_="check")
    op.drop_constraint(_TREATMENT_CK, "instrument", type_="check")
    op.drop_column("instrument", "dk_tax_treatment_source")
    op.drop_column("instrument", "dk_tax_treatment")
