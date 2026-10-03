"""add public merchant reference index

Revision ID: cb332a4e91df
Revises: bae4c90085b4
Create Date: 2026-10-03

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "cb332a4e91df"
down_revision: str | None = "bae4c90085b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "merchant_reference_generation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("source_version", sa.String(length=200), nullable=False),
        sa.Column("package_integrity", sa.String(length=200), nullable=False),
        sa.Column("catalog_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column("license", sa.String(length=32), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('staging', 'active', 'superseded', 'failed')",
            name="ck_merchant_reference_generation__status",
        ),
        sa.CheckConstraint(
            "license = 'BSD-3-Clause'",
            name="ck_merchant_reference_generation__license",
        ),
        sa.CheckConstraint(
            "record_count > 0",
            name="ck_merchant_reference_generation__record_count",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_merchant_reference_generation__source_version",
        "merchant_reference_generation",
        ["source_id", "source_version"],
        unique=False,
    )

    op.create_table(
        "merchant_reference",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generation_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("source_entity_id", sa.String(length=200), nullable=False),
        sa.Column("label", sa.String(length=256), nullable=False),
        sa.Column("category_path", sa.String(length=200), nullable=False),
        sa.Column("wikidata_id", sa.String(length=16), nullable=True),
        sa.Column("source_version", sa.String(length=200), nullable=False),
        sa.Column("source_revision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column("license", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["merchant_reference_generation.id"],
            name="fk_merchant_reference__generation_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generation_id",
            "source_id",
            "source_entity_id",
            name="uq_merchant_reference__generation_source_entity",
        ),
        sa.CheckConstraint(
            "license = 'BSD-3-Clause'",
            name="ck_merchant_reference__license",
        ),
    )
    op.create_index(
        "ix_merchant_reference__generation_label",
        "merchant_reference",
        ["generation_id", "label"],
        unique=False,
    )

    op.create_table(
        "merchant_reference_alias",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generation_id", sa.Uuid(), nullable=False),
        sa.Column("reference_id", sa.Uuid(), nullable=False),
        sa.Column("alias", sa.String(length=256), nullable=False),
        sa.Column("normalized_alias", sa.String(length=256), nullable=False),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["merchant_reference_generation.id"],
            name="fk_merchant_reference_alias__generation_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reference_id"],
            ["merchant_reference.id"],
            name="fk_merchant_reference_alias__reference_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reference_id",
            "normalized_alias",
            name="uq_merchant_reference_alias__reference_normalized",
        ),
    )
    op.create_index(
        "ix_merchant_reference_alias__generation_normalized",
        "merchant_reference_alias",
        ["generation_id", "normalized_alias"],
        unique=False,
    )

    op.create_table(
        "merchant_reference_refresh_state",
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("active_generation_id", sa.Uuid(), nullable=True),
        sa.Column("candidate_version", sa.String(length=200), nullable=True),
        sa.Column("candidate_integrity", sa.String(length=200), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status in ('never_refreshed', 'refreshing', 'current', 'stale', 'failed')",
            name="ck_merchant_reference_refresh_state__status",
        ),
        sa.ForeignKeyConstraint(
            ["active_generation_id"],
            ["merchant_reference_generation.id"],
            name="fk_merchant_reference_refresh_state__active_generation_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("source_id"),
    )


def downgrade() -> None:
    op.drop_table("merchant_reference_refresh_state")
    op.drop_index(
        "ix_merchant_reference_alias__generation_normalized",
        table_name="merchant_reference_alias",
    )
    op.drop_table("merchant_reference_alias")
    op.drop_index(
        "ix_merchant_reference__generation_label",
        table_name="merchant_reference",
    )
    op.drop_table("merchant_reference")
    op.drop_index(
        "ix_merchant_reference_generation__source_version",
        table_name="merchant_reference_generation",
    )
    op.drop_table("merchant_reference_generation")
