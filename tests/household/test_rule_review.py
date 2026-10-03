"""Conflicting learned evidence invalidates defaults, not human overrides."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from penge.household import models as m
from penge.household import schemas as s
from penge.household import service


def test_conflict_reviews_existing_rule_assignment_and_keeps_manual(
    session: Session,
    synthetic_sources: dict[str, uuid.UUID],
) -> None:
    first = service.save_category(
        session,
        s.CategoryWrite(
            expected_revision=0,
            name="Synthetic Original",
            kind="expense",
        ),
    )
    other = service.save_category(
        session,
        s.CategoryWrite(
            expected_revision=0,
            name="Synthetic Correction",
            kind="expense",
        ),
    )
    merchant = service.save_merchant(
        session,
        s.MerchantWrite(
            expected_revision=0,
            name="Synthetic Market",
            identity_kind="stable",
            confirmed=True,
        ),
    )
    for provider in ("gls", "lunar"):
        service.save_alias(
            session,
            s.AliasWrite(
                expected_revision=0,
                merchant_id=merchant.id,
                provider=provider,
                label="Synthetic Market",
                confirmed=True,
            ),
        )
    manual = service.save_classification(
        session,
        synthetic_sources["ebank"],
        s.ClassificationWrite(
            expected_revision=0,
            treatment="expense",
            merchant_id=merchant.id,
            identity_confirmed=True,
            explanation="synthetic original evidence",
            allocations=[s.Split(category_id=first.id, amount=Decimal("-12.34"))],
        ),
    )
    rule = service.latest_rule(session, merchant)
    assert rule is not None and rule.state == "active"
    service.on_bank_sync(session, inserted_ids=[synthetic_sources["gls"]], changed_ids=[])
    automatic = service.require(session, m.Classification, synthetic_sources["gls"])
    assert automatic.provenance == "rule" and automatic.review_state == "classified"
    service.save_classification(
        session,
        synthetic_sources["ebank"],
        s.ClassificationWrite(
            expected_revision=manual.revision,
            treatment="expense",
            merchant_id=merchant.id,
            identity_confirmed=True,
            explanation="synthetic conflicting correction",
            allocations=[s.Split(category_id=other.id, amount=Decimal("-12.34"))],
        ),
    )
    reviewed = service.require(session, m.Classification, automatic.transaction_id)
    assert reviewed.review_state == "needs_review" and reviewed.revision == 2
    assert service.classification_out(session, automatic).allocations == [
        s.Split(category_id=first.id, amount=Decimal("-12.34")),
    ]
    assert manual.review_state == "classified" and manual.provenance == "manual"
    assert (
        service.on_bank_sync(session, inserted_ids=[synthetic_sources["lunar"]], changed_ids=[])
        == 0
    )
    assert session.get(m.Classification, synthetic_sources["lunar"]) is None


def test_processor_only_label_never_becomes_a_confirmed_alias(session: Session) -> None:
    merchant = service.save_merchant(
        session,
        s.MerchantWrite(
            expected_revision=0,
            name="Synthetic Grocer",
            identity_kind="stable",
            confirmed=True,
        ),
    )
    with pytest.raises(service.HouseholdError, match="processor-only"):
        service.save_alias(
            session,
            s.AliasWrite(
                expected_revision=0,
                merchant_id=merchant.id,
                provider="gls",
                label="PAYPAL Europe S.a.r.l. et Cie, S.C.A.",
                confirmed=True,
            ),
        )
