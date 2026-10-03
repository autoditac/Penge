"""Historical approval must cover exact source identity, not only normalized aliases."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from penge.household import models as m
from penge.household import schemas as s
from penge.household import service


@pytest.mark.parametrize("field", ["kind", "counterparty"])
def test_preview_rejects_changed_source_identity(
    session: Session,
    synthetic_sources: dict[str, uuid.UUID],
    field: str,
) -> None:
    category = service.save_category(
        session,
        s.CategoryWrite(expected_revision=0, name="Synthetic Groceries", kind="expense"),
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
    service.save_alias(
        session,
        s.AliasWrite(
            expected_revision=0,
            merchant_id=merchant.id,
            provider="gls",
            label="Synthetic Market",
            confirmed=True,
        ),
    )
    service.save_classification(
        session,
        synthetic_sources["ebank"],
        s.ClassificationWrite(
            expected_revision=0,
            treatment="expense",
            merchant_id=merchant.id,
            identity_confirmed=True,
            explanation="synthetic evidence",
            allocations=[s.Split(category_id=category.id, amount=Decimal("-12.34"))],
        ),
    )
    rule = service.latest_rule(session, merchant)
    assert rule is not None
    preview = service.preview_rule(session, rule.id, 100, 0)
    assert len(preview.candidates) == 1
    transaction = service.require(session, m.SourceTransaction, synthetic_sources["gls"])
    if field == "kind":
        transaction.kind = "corrected_source_kind"
    else:
        transaction.counterparty = "SYNTHETIC MARKET"
    session.flush()
    with pytest.raises(service.HouseholdError, match="preview is stale"):
        service.apply_preview(session, preview.id)
    assert session.get(m.Classification, transaction.id) is None
