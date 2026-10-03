"""Typed persistence contracts for ADR-0050.

Source models map only columns needed for reads; migrations never create them
from this metadata. Categorization writes never mutate these models.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from penge.household.schemas import ReviewState


class Base(DeclarativeBase):
    """Household ORM metadata."""


def now() -> datetime:
    """UTC timestamp for audit events."""
    return datetime.now(UTC)


class Account(Base):
    """Read-only projection of canonical account columns."""

    __tablename__ = "account"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    provider: Mapped[str] = mapped_column(String)
    currency: Mapped[str] = mapped_column(String(3))
    external_id: Mapped[str | None] = mapped_column(String)


class SourceTransaction(Base):
    """Read-only projection; source identity survives upserts."""

    __tablename__ = "transaction"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("account.id"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    kind: Mapped[str] = mapped_column(String)
    counterparty: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String)


class Category(Base):
    """Stable editable financial category, never a transfer/review state."""

    __tablename__ = "household_category"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(10))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("household_category.id", name="fk_household_category__parent_id")
    )
    sort_order: Mapped[int] = mapped_column(default=0)
    archived: Mapped[bool] = mapped_column(default=False)
    revision: Mapped[int] = mapped_column(default=1)


class Merchant(Base):
    """Household identity, separate from source labels/public suggestions."""

    __tablename__ = "household_merchant"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    identity_kind: Mapped[str] = mapped_column(String(20), default="unknown")
    confirmed: Mapped[bool] = mapped_column(default=False)
    archived: Mapped[bool] = mapped_column(default=False)
    revision: Mapped[int] = mapped_column(default=1)
    rule_version: Mapped[int] = mapped_column(default=0)
    reference_source: Mapped[str | None] = mapped_column(String(200))
    reference_key: Mapped[str | None] = mapped_column(String(200))
    reference_version: Mapped[str | None] = mapped_column(String(200))


class Alias(Base):
    """Provider-scoped exact normalized match; corrections are revisioned."""

    __tablename__ = "household_merchant_alias"
    __table_args__ = (
        UniqueConstraint("provider", "normalized", name="ux_household_alias__provider_normalized"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household_merchant.id", name="fk_household_alias__merchant_id")
    )
    provider: Mapped[str] = mapped_column(String(100))
    normalized: Mapped[str] = mapped_column(String(500))
    confirmed: Mapped[bool] = mapped_column(default=False)
    revision: Mapped[int] = mapped_column(default=1)


class Rule(Base):
    """Append-only deterministic rule versions and their evidence."""

    __tablename__ = "household_rule"
    __table_args__ = (
        UniqueConstraint("merchant_id", "version", name="ux_household_rule__merchant_version"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household_merchant.id", name="fk_household_rule__merchant_id")
    )
    version: Mapped[int]
    state: Mapped[str] = mapped_column(String(20))
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("household_category.id", name="fk_household_rule__category_id")
    )
    treatment: Mapped[str | None] = mapped_column(String(20))
    explanation: Mapped[str] = mapped_column(String(1000))
    evidence: Mapped[list[dict[str, object]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Classification(Base):
    """One effective correction, independently revisioned from source facts."""

    __tablename__ = "household_classification"
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transaction.id", name="fk_household_classification__transaction_id"),
        primary_key=True,
    )
    treatment: Mapped[str] = mapped_column(String(20))
    review_state: Mapped[ReviewState] = mapped_column(String(20))
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("household_merchant.id", name="fk_household_classification__merchant_id")
    )
    identity_confirmed: Mapped[bool] = mapped_column(default=False)
    provenance: Mapped[str] = mapped_column(String(20))
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("household_rule.id", name="fk_household_classification__rule_id")
    )
    revision: Mapped[int] = mapped_column(default=1)
    source_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    source_currency: Mapped[str] = mapped_column(String(3))
    source_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_counterparty: Mapped[str | None] = mapped_column(String)
    source_kind: Mapped[str] = mapped_column(String(100))
    explanation: Mapped[str] = mapped_column(String(1000))


class Allocation(Base):
    """Signed source-currency allocation; refund credits reduce expenses."""

    __tablename__ = "household_allocation"
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household_classification.transaction_id", name="fk_household_allocation__txn"),
        primary_key=True,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household_category.id", name="fk_household_allocation__category_id"),
        primary_key=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))


class Link(Base):
    """Many-to-many reconciliation references; never substitutes source amounts."""

    __tablename__ = "household_transaction_link"
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household_classification.transaction_id", name="fk_household_link__txn"),
        primary_key=True,
    )
    related_transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transaction.id", name="fk_household_link__related_txn"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(20), primary_key=True)


class PaymentDetail(Base):
    """Non-ledger provider detail; never an account, cash balance or expense."""

    __tablename__ = "household_payment_detail"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "source_account_id",
            "external_id",
            name="ux_household_detail__source_key",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(100))
    source_account_id: Mapped[str] = mapped_column(String(200))
    external_id: Mapped[str] = mapped_column(String(200))
    connection_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    currency: Mapped[str] = mapped_column(String(3))
    merchant_name: Mapped[str | None] = mapped_column(String(500))
    reference: Mapped[str | None] = mapped_column(String(500))
    event_kind: Mapped[str] = mapped_column(String(20))
    source_fields: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    revision: Mapped[int] = mapped_column(default=1)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DetailLink(Base):
    """Approved bank-currency enrichment, retained when provider detail changes."""

    __tablename__ = "household_payment_detail_link"
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household_classification.transaction_id", name="fk_household_detail_link__txn"),
        primary_key=True,
    )
    detail_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household_payment_detail.id", name="fk_household_detail_link__detail"),
        primary_key=True,
    )
    bank_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    detail_revision: Mapped[int]


class Audit(Base):
    """Append-only snapshots; deliberately excludes raw descriptions/payloads."""

    __tablename__ = "household_audit"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    subject_type: Mapped[str] = mapped_column(String(30))
    subject_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    action: Mapped[str] = mapped_column(String(30))
    actor: Mapped[str] = mapped_column(String(100), default="household")
    before: Mapped[dict[str, object] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    after: Mapped[dict[str, object]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Preview(Base):
    """Persisted explicit-approval batch; apply checks every recorded revision."""

    __tablename__ = "household_rule_preview"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("household_rule.id", name="fk_household_preview__rule_id")
    )
    candidates: Mapped[list[dict[str, object]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    applied: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
