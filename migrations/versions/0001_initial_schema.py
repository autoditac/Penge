"""initial schema

Creates the nine core tables of the Penge data model:

    entity, account, instrument, transaction, holding_snapshot,
    price_history, fx_rate, document, tax_lot.

Conventions (per ``.github/instructions/migrations.instructions.md``):

- Money columns are ``Numeric(20, 4)``; never ``Float``.
- Quantities use ``Numeric(28, 8)`` to accommodate fractional crypto.
- FX rates use ``Numeric(20, 8)``.
- Timestamps are ``TIMESTAMP WITH TIME ZONE`` and store UTC.
- Foreign keys are explicit and named ``fk_<table>__<column>``.
- Indexes are explicit and named ``ix_<table>__<column(s)>``.
- Surrogate primary keys are UUIDs (``gen_random_uuid()`` from
  ``pgcrypto``).

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-07 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UUID_PK = sa.Column(
    "id",
    postgresql.UUID(as_uuid=True),
    primary_key=True,
    server_default=sa.text("gen_random_uuid()"),
)


def _money(name: str, *, nullable: bool = True, default: str | None = None) -> sa.Column:
    kwargs: dict[str, object] = {"nullable": nullable}
    if default is not None:
        kwargs["server_default"] = sa.text(default)
    return sa.Column(name, sa.Numeric(20, 4), **kwargs)


def _qty(name: str, *, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.Numeric(28, 8), nullable=nullable)


def _ts(name: str, *, nullable: bool = True, default_now: bool = False) -> sa.Column:
    kwargs: dict[str, object] = {"nullable": nullable}
    if default_now:
        kwargs["server_default"] = sa.text("now()")
    return sa.Column(name, sa.DateTime(timezone=True), **kwargs)


def upgrade() -> None:
    # ``gen_random_uuid()`` lives in pgcrypto; safe to install if absent.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "entity",
        _UUID_PK,
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        _ts("created_at", nullable=False, default_now=True),
        _ts("updated_at", nullable=False, default_now=True),
    )

    op.create_table(
        "account",
        _UUID_PK,
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("external_id", sa.Text, nullable=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("iban", sa.Text, nullable=True),
        _ts("opened_at"),
        _ts("closed_at"),
        _ts("created_at", nullable=False, default_now=True),
        _ts("updated_at", nullable=False, default_now=True),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entity.id"], name="fk_account__entity_id", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("provider", "external_id", name="ux_account__provider_external_id"),
    )
    op.create_index("ix_account__entity_id", "account", ["entity_id"])

    op.create_table(
        "instrument",
        _UUID_PK,
        sa.Column("isin", sa.CHAR(12), nullable=True),
        sa.Column("ticker", sa.Text, nullable=True),
        sa.Column("mic", sa.CHAR(4), nullable=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        _ts("created_at", nullable=False, default_now=True),
        _ts("updated_at", nullable=False, default_now=True),
        sa.UniqueConstraint("isin", name="ux_instrument__isin"),
    )
    op.create_index("ix_instrument__ticker", "instrument", ["ticker"])

    op.create_table(
        "transaction",
        _UUID_PK,
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), nullable=True),
        _ts("ts", nullable=False),
        sa.Column("value_date", sa.Date, nullable=True),
        sa.Column("kind", sa.Text, nullable=False),
        _qty("quantity"),
        _money("price"),
        _money("amount", nullable=False),
        _money("fee", default="0"),
        _money("tax", default="0"),
        sa.Column("fx_rate", sa.Numeric(20, 8), nullable=True),
        sa.Column("counterparty", sa.Text, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("external_id", sa.Text, nullable=True),
        sa.Column("raw", postgresql.JSONB, nullable=True),
        _ts("created_at", nullable=False, default_now=True),
        sa.ForeignKeyConstraint(
            ["account_id"], ["account.id"], name="fk_transaction__account_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instrument.id"],
            name="fk_transaction__instrument_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "account_id", "external_id", name="ux_transaction__account_id_external_id"
        ),
    )
    op.create_index("ix_transaction__account_id_ts", "transaction", ["account_id", "ts"])
    op.create_index(
        "ix_transaction__instrument_id_ts",
        "transaction",
        ["instrument_id", "ts"],
        postgresql_where=sa.text("instrument_id IS NOT NULL"),
    )

    op.create_table(
        "holding_snapshot",
        _UUID_PK,
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("as_of", sa.Date, nullable=False),
        _qty("quantity", nullable=False),
        _money("price"),
        _money("market_value"),
        _money("cost_basis"),
        _ts("created_at", nullable=False, default_now=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["account.id"],
            name="fk_holding_snapshot__account_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instrument.id"],
            name="fk_holding_snapshot__instrument_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "account_id",
            "instrument_id",
            "as_of",
            name="ux_holding_snapshot__account_instrument_as_of",
        ),
    )
    op.create_index("ix_holding_snapshot__as_of", "holding_snapshot", ["as_of"])

    op.create_table(
        "price_history",
        _UUID_PK,
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("as_of", sa.Date, nullable=False),
        _money("close", nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("source", sa.Text, nullable=True),
        _ts("created_at", nullable=False, default_now=True),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instrument.id"],
            name="fk_price_history__instrument_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("instrument_id", "as_of", name="ux_price_history__instrument_id_as_of"),
    )

    op.create_table(
        "fx_rate",
        _UUID_PK,
        sa.Column("as_of", sa.Date, nullable=False),
        sa.Column("base_ccy", sa.CHAR(3), nullable=False),
        sa.Column("quote_ccy", sa.CHAR(3), nullable=False),
        sa.Column("rate", sa.Numeric(20, 8), nullable=False),
        sa.Column("source", sa.Text, nullable=True),
        _ts("created_at", nullable=False, default_now=True),
        sa.UniqueConstraint("as_of", "base_ccy", "quote_ccy", name="ux_fx_rate__as_of_base_quote"),
    )
    op.create_index("ix_fx_rate__as_of", "fx_rate", ["as_of"])

    op.create_table(
        "document",
        _UUID_PK,
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("issued_at", sa.Date, nullable=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("storage_uri", sa.Text, nullable=False),
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column("bytes", sa.BigInteger, nullable=True),
        sa.Column("mime", sa.Text, nullable=True),
        _ts("created_at", nullable=False, default_now=True),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entity.id"], name="fk_document__entity_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["account.id"], name="fk_document__account_id", ondelete="SET NULL"
        ),
        sa.UniqueConstraint("sha256", name="ux_document__sha256"),
    )
    op.create_index("ix_document__entity_id", "document", ["entity_id"])

    op.create_table(
        "tax_lot",
        _UUID_PK,
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("open_transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("close_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        _ts("opened_at", nullable=False),
        _ts("closed_at"),
        _qty("quantity", nullable=False),
        _money("cost_basis", nullable=False),
        _money("proceeds"),
        _money("realized_gain"),
        sa.Column("method", sa.Text, nullable=False),
        _ts("created_at", nullable=False, default_now=True),
        _ts("updated_at", nullable=False, default_now=True),
        sa.ForeignKeyConstraint(
            ["account_id"], ["account.id"], name="fk_tax_lot__account_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instrument.id"],
            name="fk_tax_lot__instrument_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["open_transaction_id"],
            ["transaction.id"],
            name="fk_tax_lot__open_transaction_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["close_transaction_id"],
            ["transaction.id"],
            name="fk_tax_lot__close_transaction_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_tax_lot__account_instrument_opened",
        "tax_lot",
        ["account_id", "instrument_id", "opened_at"],
    )


def downgrade() -> None:
    # Drop in reverse order of creation to respect foreign keys.
    op.drop_index("ix_tax_lot__account_instrument_opened", table_name="tax_lot")
    op.drop_table("tax_lot")

    op.drop_index("ix_document__entity_id", table_name="document")
    op.drop_table("document")

    op.drop_index("ix_fx_rate__as_of", table_name="fx_rate")
    op.drop_table("fx_rate")

    op.drop_table("price_history")

    op.drop_index("ix_holding_snapshot__as_of", table_name="holding_snapshot")
    op.drop_table("holding_snapshot")

    op.drop_index("ix_transaction__instrument_id_ts", table_name="transaction")
    op.drop_index("ix_transaction__account_id_ts", table_name="transaction")
    op.drop_table("transaction")

    op.drop_index("ix_instrument__ticker", table_name="instrument")
    op.drop_table("instrument")

    op.drop_index("ix_account__entity_id", table_name="account")
    op.drop_table("account")

    op.drop_table("entity")

    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
