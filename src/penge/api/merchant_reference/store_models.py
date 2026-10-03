"""ORM models for isolated public merchant-reference generations."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class ReferenceBase(DeclarativeBase):
    """Declarative base for the isolated public-reference tables."""


class MerchantReferenceGeneration(ReferenceBase):
    """One immutable, fully validated source snapshot."""

    __tablename__ = "merchant_reference_generation"
    __table_args__ = (
        CheckConstraint(
            "status in ('staging', 'active', 'superseded', 'failed')",
            name="ck_merchant_reference_generation__status",
        ),
        CheckConstraint(
            "license = 'BSD-3-Clause'",
            name="ck_merchant_reference_generation__license",
        ),
        CheckConstraint(
            "record_count > 0",
            name="ck_merchant_reference_generation__record_count",
        ),
        Index(
            "ix_merchant_reference_generation__source_version",
            "source_id",
            "source_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_version: Mapped[str] = mapped_column(String(200), nullable=False)
    package_integrity: Mapped[str] = mapped_column(String(200), nullable=False)
    catalog_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    license: Mapped[str] = mapped_column(String(32), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    references: Mapped[list[MerchantReference]] = relationship(
        back_populates="generation",
        cascade="all, delete-orphan",
    )


class MerchantReference(ReferenceBase):
    """One public catalog entity in one immutable generation."""

    __tablename__ = "merchant_reference"
    __table_args__ = (
        UniqueConstraint(
            "generation_id",
            "source_id",
            "source_entity_id",
            name="uq_merchant_reference__generation_source_entity",
        ),
        CheckConstraint(
            "license = 'BSD-3-Clause'",
            name="ck_merchant_reference__license",
        ),
        Index(
            "ix_merchant_reference__generation_label",
            "generation_id",
            "label",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    generation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "merchant_reference_generation.id",
            name="fk_merchant_reference__generation_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_entity_id: Mapped[str] = mapped_column(String(200), nullable=False)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    category_path: Mapped[str] = mapped_column(String(200), nullable=False)
    wikidata_id: Mapped[str | None] = mapped_column(String(16))
    source_version: Mapped[str] = mapped_column(String(200), nullable=False)
    source_revision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    license: Mapped[str] = mapped_column(String(32), nullable=False)

    generation: Mapped[MerchantReferenceGeneration] = relationship(back_populates="references")
    aliases: Mapped[list[MerchantReferenceAlias]] = relationship(
        back_populates="reference",
        cascade="all, delete-orphan",
        order_by="MerchantReferenceAlias.normalized_alias",
    )


class MerchantReferenceAlias(ReferenceBase):
    """One literal public alias indexed only inside Penge."""

    __tablename__ = "merchant_reference_alias"
    __table_args__ = (
        UniqueConstraint(
            "reference_id",
            "normalized_alias",
            name="uq_merchant_reference_alias__reference_normalized",
        ),
        Index(
            "ix_merchant_reference_alias__generation_normalized",
            "generation_id",
            "normalized_alias",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    generation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "merchant_reference_generation.id",
            name="fk_merchant_reference_alias__generation_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    reference_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "merchant_reference.id",
            name="fk_merchant_reference_alias__reference_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    alias: Mapped[str] = mapped_column(String(256), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(256), nullable=False)

    reference: Mapped[MerchantReference] = relationship(back_populates="aliases")


class MerchantReferenceRefreshState(ReferenceBase):
    """Current active generation and most recent refresh outcome per source."""

    __tablename__ = "merchant_reference_refresh_state"
    __table_args__ = (
        CheckConstraint(
            "status in ('never_refreshed', 'refreshing', 'current', 'stale', 'failed')",
            name="ck_merchant_reference_refresh_state__status",
        ),
    )

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    active_generation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "merchant_reference_generation.id",
            name="fk_merchant_reference_refresh_state__active_generation_id",
            ondelete="RESTRICT",
        ),
    )
    candidate_version: Mapped[str | None] = mapped_column(String(200))
    candidate_integrity: Mapped[str | None] = mapped_column(String(200))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    active_generation: Mapped[MerchantReferenceGeneration | None] = relationship(
        foreign_keys=[active_generation_id]
    )
