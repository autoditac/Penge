"""Guarded local household correction/review API (ADR-0050).

Like imports, this surface inherits the deployment's authenticated reverse
proxy boundary, not an Enable Banking signing-key dependency. It is explicitly
opt-in and uses the shared write engine and refresh lock/pending marker.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from penge.api.connections.config import ConnectionsConfig
from penge.api.imports.engine import get_import_engine
from penge.household import models as m
from penge.household import schemas as s
from penge.household import service
from penge.ops.net_worth_refresh import (
    LockUnavailableError,
    RefreshStateError,
    refresh_write_intent,
)

router = APIRouter(prefix="/household", tags=["household"])
Limit = Annotated[int, Query(ge=1, le=500)]
Offset = Annotated[int, Query(ge=0)]


def require_enabled() -> None:
    """Disable household access unless the trusted deployment explicitly opts in."""
    if os.environ.get("PENGE_HOUSEHOLD_ENABLED", "").lower() != "true":
        raise HTTPException(503, "household categorization is disabled")


def read_session(_: Annotated[None, Depends(require_enabled)]) -> Iterator[Session]:
    """Read canonical facts/corrections directly, without waiting for dbt refresh."""
    try:
        with Session(get_import_engine()) as session:
            session.info["household_read_only"] = True
            yield session
    except service.HouseholdError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


def write_session(_: Annotated[None, Depends(require_enabled)]) -> Iterator[Session]:
    """Commit corrections, audit and refresh intent atomically at the guarded boundary."""
    config = ConnectionsConfig.from_env()
    try:
        with (
            refresh_write_intent(
                lock_file=config.refresh_state_dir / "refresh.lock",
                pending_refresh_file=config.refresh_state_dir / "pending",
            ) as observe,
            Session(get_import_engine()) as session,
            session.begin(),
        ):
            yield session
            # Mark intent before commit, just like source writers. A failed
            # commit may leave a conservative pending marker, never a stale mart.
            observe(1)
    except service.HouseholdError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(409, "constraint conflict; reload and review the latest state") from exc
    except (LockUnavailableError, RefreshStateError) as exc:
        raise HTTPException(503, str(exc)) from exc


Read = Annotated[Session, Depends(read_session)]
Write = Annotated[Session, Depends(write_session, scope="function")]


@router.get("/categories", response_model=list[s.CategoryOut])
def categories(session: Read, limit: Limit = 100, offset: Offset = 0) -> list[s.CategoryOut]:
    """Flat, stable-ID tree including archived categories for historical display."""
    return [
        s.CategoryOut.model_validate(row)
        for row in session.scalars(
            select(m.Category)
            .order_by(m.Category.sort_order, m.Category.id)
            .limit(limit)
            .offset(offset)
        )
    ]


@router.post("/categories", response_model=s.CategoryOut, status_code=201)
def create_category(body: s.CategoryWrite, session: Write) -> s.CategoryOut:
    return s.CategoryOut.model_validate(service.save_category(session, body))


@router.patch("/categories/{key}", response_model=s.CategoryOut)
def update_category(key: uuid.UUID, body: s.CategoryWrite, session: Write) -> s.CategoryOut:
    return s.CategoryOut.model_validate(service.save_category(session, body, key))


@router.get("/merchants", response_model=list[s.MerchantOut])
def merchants(session: Read, limit: Limit = 100, offset: Offset = 0) -> list[s.MerchantOut]:
    return [
        s.MerchantOut.model_validate(row)
        for row in session.scalars(
            select(m.Merchant).order_by(m.Merchant.name, m.Merchant.id).limit(limit).offset(offset)
        )
    ]


@router.post("/merchants", response_model=s.MerchantOut, status_code=201)
def create_merchant(body: s.MerchantWrite, session: Write) -> s.MerchantOut:
    return s.MerchantOut.model_validate(service.save_merchant(session, body))


@router.patch("/merchants/{key}", response_model=s.MerchantOut)
def update_merchant(key: uuid.UUID, body: s.MerchantWrite, session: Write) -> s.MerchantOut:
    return s.MerchantOut.model_validate(service.save_merchant(session, body, key))


@router.get("/aliases", response_model=list[s.AliasOut])
def aliases(
    session: Read,
    merchant_id: uuid.UUID | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
) -> list[s.AliasOut]:
    query = select(m.Alias).order_by(m.Alias.id).limit(limit).offset(offset)
    if merchant_id:
        query = query.where(m.Alias.merchant_id == merchant_id)
    return [s.AliasOut.model_validate(row) for row in session.scalars(query)]


@router.post("/aliases", response_model=s.AliasOut, status_code=201)
def create_alias(body: s.AliasWrite, session: Write) -> s.AliasOut:
    return s.AliasOut.model_validate(service.save_alias(session, body))


@router.patch("/aliases/{key}", response_model=s.AliasOut)
def update_alias(key: uuid.UUID, body: s.AliasWrite, session: Write) -> s.AliasOut:
    return s.AliasOut.model_validate(service.save_alias(session, body, key))


@router.get("/rules", response_model=list[s.RuleOut])
def rules(
    session: Read,
    merchant_id: uuid.UUID | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
) -> list[s.RuleOut]:
    query = select(m.Rule).order_by(m.Rule.created_at.desc(), m.Rule.id).limit(limit).offset(offset)
    if merchant_id:
        query = query.where(m.Rule.merchant_id == merchant_id)
    return [s.RuleOut.model_validate(row) for row in session.scalars(query)]


@router.patch("/rules/{key}", response_model=s.RuleOut)
def control_rule(key: uuid.UUID, body: s.RuleControl, session: Write) -> s.RuleOut:
    return s.RuleOut.model_validate(service.control_rule(session, key, body))


@router.post("/rules/{key}/preview", response_model=s.PreviewOut, status_code=201)
def preview_rule(
    key: uuid.UUID,
    session: Write,
    limit: Limit = 500,
    offset: Offset = 0,
) -> s.PreviewOut:
    """Scan a bounded chronological source page and persist eligible changes."""
    return s.PreviewOut.model_validate(service.preview_rule(session, key, limit, offset))


@router.get("/previews/{key}", response_model=s.PreviewOut)
def get_preview(key: uuid.UUID, session: Read) -> s.PreviewOut:
    return s.PreviewOut.model_validate(service.require(session, m.Preview, key))


@router.post("/previews/{key}/apply", response_model=s.PreviewOut)
def apply_preview(key: uuid.UUID, body: s.ApplyPreview, session: Write) -> s.PreviewOut:
    _ = body
    return s.PreviewOut.model_validate(service.apply_preview(session, key))


def transaction_out(
    session: Session, txn: m.SourceTransaction, account: m.Account
) -> s.TransactionOut:
    record = session.get(m.Classification, txn.id)
    return s.TransactionOut(
        transaction_id=txn.id,
        account_id=txn.account_id,
        provider=account.provider,
        ts=txn.ts,
        amount=txn.amount,
        currency=account.currency,
        kind=txn.kind,
        counterparty=txn.counterparty,
        description=txn.description,
        classification=service.classification_out(session, record) if record else None,
        reporting_role="bank_movement"
        if account.provider in service.BANK_PROVIDERS
        else "other_source",
    )


@router.get("/transactions", response_model=list[s.TransactionOut])
def transactions(
    session: Read,
    limit: Limit = 100,
    offset: Offset = 0,
    account_id: uuid.UUID | None = None,
    merchant_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    treatment: s.Treatment | None = None,
    review_state: s.ReviewState | None = None,
    provider: str | None = None,
    currency: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    search: str | None = None,
) -> list[s.TransactionOut]:
    """Bounded browsing/filtering; raw JSON, account identifiers and source secrets omitted."""
    query = (
        select(m.SourceTransaction, m.Account)
        .join(m.Account, m.SourceTransaction.account_id == m.Account.id)
        .outerjoin(m.Classification, m.Classification.transaction_id == m.SourceTransaction.id)
        .where(m.Account.provider.in_(service.BANK_PROVIDERS))
    )
    filters = [
        (account_id, m.SourceTransaction.account_id),
        (merchant_id, m.Classification.merchant_id),
        (treatment, m.Classification.treatment),
        (provider, m.Account.provider),
        (currency, m.Account.currency),
    ]
    for value, column in filters:
        if value is not None:
            query = query.where(column == value)
    source_changed = and_(
        m.Classification.transaction_id.is_not(None),
        or_(
            m.Classification.source_amount.is_distinct_from(m.SourceTransaction.amount),
            m.Classification.source_currency.is_distinct_from(m.Account.currency),
            m.Classification.source_ts.is_distinct_from(m.SourceTransaction.ts),
            m.Classification.source_counterparty.is_distinct_from(m.SourceTransaction.counterparty),
            m.Classification.source_kind.is_distinct_from(m.SourceTransaction.kind),
        ),
    )
    detail_changed = (
        select(m.DetailLink.transaction_id)
        .join(m.PaymentDetail, m.DetailLink.detail_id == m.PaymentDetail.id)
        .where(
            m.DetailLink.transaction_id == m.Classification.transaction_id,
            m.DetailLink.detail_revision != m.PaymentDetail.revision,
        )
        .exists()
    )
    stale = or_(source_changed, detail_changed)
    if review_state == "unclassified":
        query = query.where(
            or_(
                m.Classification.transaction_id.is_(None),
                m.Classification.review_state == "unclassified",
            )
        )
    elif review_state == "needs_review":
        query = query.where(or_(m.Classification.review_state == "needs_review", stale))
    elif review_state:
        query = query.where(m.Classification.review_state == review_state, ~stale)
    if category_id:
        query = query.where(
            m.SourceTransaction.id.in_(
                select(m.Allocation.transaction_id).where(m.Allocation.category_id == category_id)
            )
        )
    if from_date:
        query = query.where(m.SourceTransaction.ts >= from_date)
    if to_date:
        query = query.where(m.SourceTransaction.ts <= to_date)
    if search:
        query = query.where(
            or_(
                m.SourceTransaction.counterparty.contains(search, autoescape=True),
                m.SourceTransaction.description.contains(search, autoescape=True),
            )
        )
    query = (
        query.order_by(m.SourceTransaction.ts.desc(), m.SourceTransaction.id)
        .limit(limit)
        .offset(offset)
    )
    return [transaction_out(session, txn, account) for txn, account in session.execute(query)]


@router.get("/transactions/{key}", response_model=s.TransactionOut)
def get_transaction(key: uuid.UUID, session: Read) -> s.TransactionOut:
    txn, account = service.source(session, key)
    return transaction_out(session, txn, account)


@router.get("/transactions/{key}/suggestion", response_model=s.Suggestion)
def suggestion(key: uuid.UUID, session: Read) -> s.Suggestion:
    return service.suggest(session, key)


@router.patch("/transactions/{key}/classification", response_model=s.ClassificationOut)
def correct_transaction(
    key: uuid.UUID,
    body: s.ClassificationWrite,
    session: Write,
) -> s.ClassificationOut:
    return service.classification_out(session, service.save_classification(session, key, body))


@router.post("/transactions/{key}/undo", response_model=s.ClassificationOut)
def undo_transaction(key: uuid.UUID, body: s.Undo, session: Write) -> s.ClassificationOut:
    return service.classification_out(session, service.undo_classification(session, key, body))


@router.get("/audit", response_model=list[s.AuditOut])
def history(
    session: Read,
    subject_id: uuid.UUID,
    limit: Limit = 100,
    offset: Offset = 0,
) -> list[s.AuditOut]:
    return [
        s.AuditOut.model_validate(row)
        for row in session.scalars(
            select(m.Audit)
            .where(m.Audit.subject_id == subject_id)
            .order_by(m.Audit.created_at.desc(), m.Audit.id)
            .limit(limit)
            .offset(offset)
        )
    ]


@router.get("/payment-details", response_model=list[s.PaymentDetailOut])
def payment_details(
    session: Read,
    unmatched: bool = False,
    limit: Limit = 100,
    offset: Offset = 0,
) -> list[s.PaymentDetailOut]:
    query = select(m.PaymentDetail).order_by(m.PaymentDetail.ts.desc(), m.PaymentDetail.id)
    if unmatched:
        query = query.where(~m.PaymentDetail.id.in_(select(m.DetailLink.detail_id)))
    return [
        s.PaymentDetailOut.model_validate(row)
        for row in session.scalars(query.limit(limit).offset(offset))
    ]
