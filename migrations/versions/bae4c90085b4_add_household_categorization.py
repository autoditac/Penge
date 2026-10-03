"""add household categorization

Revision ID: bae4c90085b4
Revises: 0007_account_metadata_overrides
Create Date: 2026-10-03 13:41:38.350401

"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "bae4c90085b4"
down_revision: str | None = "0007_account_metadata_overrides"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    def pk() -> sa.Column[uuid.UUID]:
        return sa.Column("id", sa.Uuid, primary_key=True)

    def fk(name: str, target: str, *, primary: bool = False) -> sa.Column[uuid.UUID]:
        return sa.Column(
            name,
            sa.Uuid,
            sa.ForeignKey(target, name=f"fk_{table}__{name}", ondelete="RESTRICT"),
            nullable=not primary,
            primary_key=primary,
        )

    def revision_column() -> sa.Column[int]:
        return sa.Column("revision", sa.Integer, nullable=False, server_default="1")

    def timestamp(name: str) -> sa.Column[datetime]:
        return sa.Column(
            name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        )

    table = "household_category"
    op.create_table(
        table,
        pk(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        fk("parent_id", f"{table}.id"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("archived", sa.Boolean, nullable=False, server_default=sa.false()),
        revision_column(),
        sa.CheckConstraint("kind in ('expense','income')", name="ck_household_category__kind"),
        sa.CheckConstraint(
            "revision > 0 and sort_order >= 0", name="ck_household_category__revision"
        ),
    )
    op.create_index("ix_household_category__parent_id", table, ["parent_id"])
    table = "household_merchant"
    op.create_table(
        table,
        pk(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("identity_kind", sa.String(20), nullable=False),
        sa.Column("confirmed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("archived", sa.Boolean, nullable=False, server_default=sa.false()),
        revision_column(),
        sa.Column("rule_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reference_source", sa.String(200)),
        sa.Column("reference_key", sa.String(200)),
        sa.Column("reference_version", sa.String(200)),
        sa.CheckConstraint(
            "identity_kind in ('stable','processor','marketplace','mixed','unknown')",
            name="ck_household_merchant__identity_kind",
        ),
        sa.CheckConstraint(
            "revision > 0 and rule_version >= 0", name="ck_household_merchant__revision"
        ),
    )
    table = "household_merchant_alias"
    op.create_table(
        table,
        pk(),
        fk("merchant_id", "household_merchant.id"),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("normalized", sa.String(500), nullable=False),
        sa.Column("confirmed", sa.Boolean, nullable=False, server_default=sa.false()),
        revision_column(),
        sa.UniqueConstraint(
            "provider", "normalized", name="ux_household_alias__provider_normalized"
        ),
    )
    op.alter_column(table, "merchant_id", nullable=False)
    op.create_index("ix_household_alias__merchant_id", table, ["merchant_id"])
    table = "household_rule"
    op.create_table(
        table,
        pk(),
        fk("merchant_id", "household_merchant.id"),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        fk("category_id", "household_category.id"),
        sa.Column("treatment", sa.String(20)),
        sa.Column("explanation", sa.String(1000), nullable=False),
        sa.Column("evidence", postgresql.JSONB, nullable=False),
        timestamp("created_at"),
        sa.UniqueConstraint("merchant_id", "version", name="ux_household_rule__merchant_version"),
        sa.CheckConstraint("version > 0", name="ck_household_rule__version"),
        sa.CheckConstraint(
            "state in ('active','conflict','disabled','insufficient')",
            name="ck_household_rule__state",
        ),
    )
    op.alter_column(table, "merchant_id", nullable=False)
    table = "household_classification"
    op.create_table(
        table,
        fk("transaction_id", "transaction.id", primary=True),
        sa.Column("treatment", sa.String(20), nullable=False),
        sa.Column("review_state", sa.String(20), nullable=False),
        fk("merchant_id", "household_merchant.id"),
        sa.Column("identity_confirmed", sa.Boolean, nullable=False),
        sa.Column("provenance", sa.String(20), nullable=False),
        fk("rule_id", "household_rule.id"),
        revision_column(),
        sa.Column("source_amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("source_currency", sa.String(3), nullable=False),
        sa.Column("source_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_counterparty", sa.Text),
        sa.Column("source_kind", sa.String(100), nullable=False),
        sa.Column("explanation", sa.String(1000), nullable=False),
        sa.CheckConstraint(
            "treatment in ('expense','income','refund','transfer','excluded','unclassified')",
            name="ck_household_classification__treatment",
        ),
        sa.CheckConstraint(
            "review_state in ('classified','needs_review','unclassified')",
            name="ck_household_classification__review_state",
        ),
        sa.CheckConstraint(
            "provenance in ('manual','rule')", name="ck_household_classification__provenance"
        ),
        sa.CheckConstraint("revision > 0", name="ck_household_classification__revision"),
    )
    op.create_index("ix_household_classification__review_state", table, ["review_state"])
    op.create_index("ix_household_classification__merchant_id", table, ["merchant_id"])
    table = "household_allocation"
    op.create_table(
        table,
        fk("transaction_id", "household_classification.transaction_id", primary=True),
        fk("category_id", "household_category.id", primary=True),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
    )
    op.create_index("ix_household_allocation__category_id", table, ["category_id"])
    table = "household_transaction_link"
    op.create_table(
        table,
        fk("transaction_id", "household_classification.transaction_id", primary=True),
        fk("related_transaction_id", "transaction.id", primary=True),
        sa.Column("kind", sa.String(20), primary_key=True),
        sa.CheckConstraint("kind in ('transfer','refund')", name="ck_household_link__kind"),
        sa.CheckConstraint(
            "transaction_id <> related_transaction_id", name="ck_household_link__self"
        ),
    )
    op.create_index("ix_household_link__related_transaction_id", table, ["related_transaction_id"])
    table = "household_payment_detail"
    op.create_table(
        table,
        pk(),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("source_account_id", sa.String(200), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("connection_id", sa.Uuid),
        timestamp("ts"),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("merchant_name", sa.String(500)),
        sa.Column("reference", sa.String(500)),
        sa.Column("event_kind", sa.String(20), nullable=False),
        sa.Column("source_fields", postgresql.JSONB, nullable=False),
        revision_column(),
        timestamp("last_seen_at"),
        sa.UniqueConstraint(
            "provider", "source_account_id", "external_id", name="ux_household_detail__source_key"
        ),
        sa.CheckConstraint(
            "event_kind in ('purchase','refund','funding','unknown')",
            name="ck_household_detail__event_kind",
        ),
        sa.CheckConstraint("revision > 0", name="ck_household_detail__revision"),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["bank_connection.id"],
            name="fk_household_detail__connection_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_household_detail__ts", table, ["ts"])
    table = "household_payment_detail_link"
    op.create_table(
        table,
        fk("transaction_id", "household_classification.transaction_id", primary=True),
        fk("detail_id", "household_payment_detail.id", primary=True),
        sa.Column("bank_amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("detail_revision", sa.Integer, nullable=False),
        sa.CheckConstraint("detail_revision > 0", name="ck_household_detail_link__revision"),
    )
    op.create_index("ix_household_detail_link__detail_id", table, ["detail_id"])
    table = "household_audit"
    op.create_table(
        table,
        pk(),
        sa.Column("subject_type", sa.String(30), nullable=False),
        sa.Column("subject_id", sa.Uuid, nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("before", postgresql.JSONB),
        sa.Column("after", postgresql.JSONB, nullable=False),
        timestamp("created_at"),
    )
    op.create_index("ix_household_audit__subject_id", table, ["subject_id"])
    table = "household_rule_preview"
    op.create_table(
        table,
        pk(),
        fk("rule_id", "household_rule.id"),
        sa.Column("candidates", postgresql.JSONB, nullable=False),
        sa.Column("applied", sa.Boolean, nullable=False, server_default=sa.false()),
        timestamp("created_at"),
    )
    op.alter_column(table, "rule_id", nullable=False)
    # Reject taxonomy corruption even for non-API writers. The statement
    # advisory lock serializes reparenting before the recursive row check.
    op.execute("""
        CREATE FUNCTION household_lock_category() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN PERFORM pg_advisory_xact_lock(330); RETURN NULL; END $$;
        CREATE TRIGGER household_category_lock BEFORE INSERT OR UPDATE ON household_category
        FOR EACH STATEMENT EXECUTE FUNCTION household_lock_category();
        CREATE FUNCTION household_check_category() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.parent_id = NEW.id THEN RAISE EXCEPTION 'category cycle'; END IF;
            IF EXISTS (SELECT 1 FROM household_category
                       WHERE id = NEW.parent_id AND kind <> NEW.kind)
               OR EXISTS (SELECT 1 FROM household_category
                          WHERE parent_id = NEW.id AND kind <> NEW.kind) THEN
                RAISE EXCEPTION 'cross-type category parent';
            END IF;
            IF EXISTS (
                WITH RECURSIVE ancestors AS (
                    SELECT id, parent_id FROM household_category WHERE id = NEW.parent_id
                    UNION SELECT c.id, c.parent_id FROM household_category c
                          JOIN ancestors a ON c.id = a.parent_id
                ) SELECT 1 FROM ancestors WHERE id = NEW.id
            ) THEN RAISE EXCEPTION 'category cycle'; END IF;
            IF TG_OP = 'UPDATE' AND NEW.kind <> OLD.kind THEN
                RAISE EXCEPTION 'category kind is immutable';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER household_category_guard BEFORE INSERT OR UPDATE ON household_category
        FOR EACH ROW EXECUTE FUNCTION household_check_category();
        CREATE FUNCTION household_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'household history is append-only'; END $$;
        CREATE TRIGGER household_audit_guard BEFORE UPDATE OR DELETE ON household_audit
        FOR EACH ROW EXECUTE FUNCTION household_append_only();
        CREATE TRIGGER household_rule_guard BEFORE UPDATE OR DELETE ON household_rule
        FOR EACH ROW EXECUTE FUNCTION household_append_only();
    """)
    roots = {
        "expense": [
            "Housing",
            "Groceries",
            "Dining",
            "Transport",
            "Children",
            "Health",
            "Insurance",
            "Shopping",
            "Leisure",
            "Travel",
            "Subscriptions",
            "Taxes/Fees",
            "Other",
        ],
        "income": ["Salary", "Benefits", "Interest/Dividends", "Other"],
    }
    category = sa.table(
        "household_category",
        sa.column("id", sa.Uuid),
        sa.column("name"),
        sa.column("kind"),
        sa.column("sort_order"),
    )
    for kind, names in roots.items():
        op.bulk_insert(
            category,
            [
                {
                    "id": uuid.uuid5(uuid.NAMESPACE_URL, f"penge:household:{kind}:{name}"),
                    "name": name,
                    "kind": kind,
                    "sort_order": order,
                }
                for order, name in enumerate(names)
            ],
        )


def downgrade() -> None:
    for table in (
        "household_rule_preview",
        "household_audit",
        "household_payment_detail_link",
        "household_payment_detail",
        "household_transaction_link",
        "household_allocation",
        "household_classification",
        "household_rule",
        "household_merchant_alias",
        "household_merchant",
        "household_category",
    ):
        op.drop_table(table)
    op.execute("DROP FUNCTION household_append_only()")
    op.execute("DROP FUNCTION household_check_category()")
    op.execute("DROP FUNCTION household_lock_category()")
