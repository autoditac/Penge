"""Strict HTTP contracts; Decimal money serializes as strings."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CategoryKind = Literal["expense", "income"]
Treatment = Literal["expense", "income", "refund", "transfer", "excluded", "unclassified"]
ReviewState = Literal["classified", "needs_review", "unclassified"]
IdentityKind = Literal["stable", "processor", "marketplace", "mixed", "unknown"]


class Contract(BaseModel):
    """Reject misspelled fields and expose typed ORM responses."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class Revision(Contract):
    expected_revision: int = Field(ge=0)


class CategoryWrite(Revision):
    name: str = Field(min_length=1, max_length=200)
    kind: CategoryKind
    parent_id: uuid.UUID | None = None
    sort_order: int = Field(default=0, ge=0)
    archived: bool = False


class CategoryOut(Contract):
    id: uuid.UUID
    name: str
    kind: CategoryKind
    parent_id: uuid.UUID | None
    sort_order: int
    archived: bool
    revision: int


class MerchantWrite(Revision):
    name: str = Field(min_length=1, max_length=200)
    identity_kind: IdentityKind = "unknown"
    confirmed: bool = False
    archived: bool = False
    reference_source: str | None = Field(default=None, max_length=200)
    reference_key: str | None = Field(default=None, max_length=200)
    reference_version: str | None = Field(default=None, max_length=200)


class MerchantOut(Contract):
    id: uuid.UUID
    name: str
    identity_kind: IdentityKind
    confirmed: bool
    archived: bool
    revision: int
    rule_version: int
    reference_source: str | None
    reference_key: str | None
    reference_version: str | None


class AliasWrite(Revision):
    merchant_id: uuid.UUID
    provider: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=500)
    confirmed: bool = False


class AliasOut(Contract):
    id: uuid.UUID
    merchant_id: uuid.UUID
    provider: str
    normalized: str
    confirmed: bool
    revision: int


class Split(Contract):
    category_id: uuid.UUID
    amount: Decimal = Field(max_digits=20, decimal_places=4, allow_inf_nan=False)


class ReconciliationLink(Contract):
    related_transaction_id: uuid.UUID
    kind: Literal["transfer", "refund"]


class PaymentDetailLink(Contract):
    detail_id: uuid.UUID
    detail_revision: int = Field(ge=1)
    bank_amount: Decimal = Field(max_digits=20, decimal_places=4, allow_inf_nan=False)


class ClassificationWrite(Revision):
    treatment: Treatment
    merchant_id: uuid.UUID | None = None
    identity_confirmed: bool = False
    allocations: list[Split] = Field(default_factory=list, max_length=100)
    links: list[ReconciliationLink] = Field(default_factory=list, max_length=100)
    detail_links: list[PaymentDetailLink] = Field(default_factory=list, max_length=100)
    explanation: str = Field(min_length=1, max_length=1000)


class ClassificationOut(Contract):
    transaction_id: uuid.UUID
    treatment: Treatment
    review_state: ReviewState
    merchant_id: uuid.UUID | None
    identity_confirmed: bool
    provenance: Literal["manual", "rule"]
    rule_id: uuid.UUID | None
    revision: int
    source_amount: Decimal
    source_currency: str
    source_ts: datetime
    source_counterparty: str | None
    source_kind: str
    explanation: str
    allocations: list[Split]
    links: list[ReconciliationLink]
    detail_links: list[PaymentDetailLink]
    detail_changed: bool = False
    source_changed: bool = False


class RuleOut(Contract):
    id: uuid.UUID
    merchant_id: uuid.UUID
    version: int
    state: Literal["active", "conflict", "disabled", "insufficient"]
    category_id: uuid.UUID | None
    treatment: Treatment | None
    explanation: str
    evidence: list[dict[str, object]]
    created_at: datetime


class RuleControl(Contract):
    expected_version: int = Field(ge=1)
    disabled: bool


class Suggestion(Contract):
    transaction_id: uuid.UUID
    merchant_id: uuid.UUID | None
    rule: RuleOut | None
    explanation: str
    source_hint: str | None = None


class Candidate(Contract):
    transaction_id: uuid.UUID
    expected_revision: int
    source_amount: Decimal
    source_currency: str
    source_ts: datetime
    source_kind: str
    source_counterparty: str | None
    provider: str
    normalized_counterparty: str
    alias_id: uuid.UUID | None
    alias_revision: int | None


class PreviewOut(Contract):
    id: uuid.UUID
    rule_id: uuid.UUID
    candidates: list[Candidate]
    applied: bool
    created_at: datetime


class ApplyPreview(Contract):
    approve: Literal[True]


class Undo(Revision):
    audit_id: uuid.UUID


class AuditOut(Contract):
    id: uuid.UUID
    subject_type: str
    subject_id: uuid.UUID
    action: str
    actor: str
    before: dict[str, object] | None
    after: dict[str, object]
    created_at: datetime


class TransactionOut(Contract):
    transaction_id: uuid.UUID
    account_id: uuid.UUID
    provider: str
    ts: datetime
    amount: Decimal
    currency: str
    kind: str
    counterparty: str | None
    description: str | None
    classification: ClassificationOut | None
    reporting_role: Literal["bank_movement", "detail_only", "other_source"]


class PaymentSourceFields(Contract):
    """Provider whitelist, not an arbitrary response/profile blob."""

    entry_reference: str | None = Field(default=None, max_length=200)
    transaction_id: str | None = Field(default=None, max_length=200)
    merchant_category_code: str | None = Field(default=None, max_length=10)
    bank_code: str | None = Field(default=None, max_length=100)
    bank_sub_code: str | None = Field(default=None, max_length=100)
    transaction_date: datetime | None = None


class PaymentDetailWrite(Contract):
    provider: Literal["paypal"]
    source_account_id: str = Field(min_length=1, max_length=200)
    external_id: str = Field(min_length=1, max_length=200)
    connection_id: uuid.UUID | None = None
    ts: datetime
    amount: Decimal = Field(max_digits=20, decimal_places=4, allow_inf_nan=False)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    merchant_name: str | None = Field(default=None, max_length=500)
    reference: str | None = Field(default=None, max_length=500)
    event_kind: Literal["purchase", "refund", "funding", "unknown"]
    source_fields: PaymentSourceFields = Field(default_factory=PaymentSourceFields)


class PaymentDetailOut(PaymentDetailWrite):
    id: uuid.UUID
    revision: int
    last_seen_at: datetime
