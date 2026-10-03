"""Service invariants against synthetic SQLite source projections."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from penge.household import models as m
from penge.household import schemas as s
from penge.household import service


def create_category(
    session: Session,
    name: str,
    kind: Literal["expense", "income"] = "expense",
    *,
    parent_id: uuid.UUID | None = None,
) -> m.Category:
    """Create a category through the revisioned service surface."""
    return service.save_category(
        session,
        s.CategoryWrite(
            expected_revision=0,
            name=name,
            kind=kind,
            parent_id=parent_id,
        ),
    )


def create_merchant(
    session: Session,
    name: str = "Synthetic Merchant",
    *,
    identity_kind: Literal["stable", "processor", "marketplace", "mixed", "unknown"] = "stable",
    confirmed: bool = True,
) -> m.Merchant:
    """Create a synthetic merchant with explicit identity state."""
    return service.save_merchant(
        session,
        s.MerchantWrite(
            expected_revision=0,
            name=name,
            identity_kind=identity_kind,
            confirmed=confirmed,
        ),
    )


def classification_body(
    category: m.Category,
    amount: Decimal,
    *,
    revision: int = 0,
    treatment: Literal[
        "expense", "income", "refund", "transfer", "excluded", "unclassified"
    ] = "expense",
    merchant_id: uuid.UUID | None = None,
    identity_confirmed: bool = False,
    explanation: str = "Synthetic human-reviewed classification",
) -> s.ClassificationWrite:
    """Build a fully typed classification write from synthetic facts."""
    return s.ClassificationWrite(
        expected_revision=revision,
        treatment=treatment,
        merchant_id=merchant_id,
        identity_confirmed=identity_confirmed,
        allocations=[s.Split(category_id=category.id, amount=amount)],
        explanation=explanation,
    )


def learnable_merchant(
    session: Session,
    sources: dict[str, uuid.UUID],
    category: m.Category,
    *,
    identity_kind: Literal["stable", "processor", "marketplace", "mixed", "unknown"] = "stable",
) -> tuple[m.Merchant, m.Rule]:
    """Record one audited, unambiguous human confirmation and return its rule."""
    merchant = create_merchant(session, identity_kind=identity_kind)
    service.save_classification(
        session,
        sources["ebank"],
        classification_body(
            category,
            Decimal("-12.34"),
            merchant_id=merchant.id,
            identity_confirmed=True,
        ),
    )
    rule = service.latest_rule(session, merchant)
    assert rule is not None
    return merchant, rule


def test_category_edits_keep_historical_assignments(
    session: Session, synthetic_sources: dict[str, uuid.UUID]
) -> None:
    category = create_category(session, "Food")
    parent = create_category(session, "Living")
    source_id = synthetic_sources["gls"]
    service.save_classification(
        session, source_id, classification_body(category, Decimal("-12.34"))
    )

    renamed = service.save_category(
        session,
        s.CategoryWrite(
            expected_revision=category.revision,
            name="Groceries",
            kind="expense",
            parent_id=parent.id,
            archived=True,
        ),
        category.id,
    )

    record = session.get(m.Classification, source_id)
    assert record is not None
    saved = service.classification_out(session, record)
    assert renamed.id == category.id
    assert renamed.revision == 2
    assert saved.allocations == [s.Split(category_id=category.id, amount=Decimal("-12.34"))]
    assert renamed.name == "Groceries"
    assert renamed.archived


def test_category_cycle_and_cross_kind_parent_are_rejected(session: Session) -> None:
    parent = create_category(session, "Parent")
    child = create_category(session, "Child", parent_id=parent.id)
    income = create_category(session, "Income", kind="income")

    with pytest.raises(service.HouseholdError, match="cycle"):
        service.save_category(
            session,
            s.CategoryWrite(
                expected_revision=child.revision,
                name="Parent",
                kind="expense",
                parent_id=child.id,
            ),
            parent.id,
        )
    with pytest.raises(service.HouseholdError, match="same financial type"):
        service.save_category(
            session,
            s.CategoryWrite(
                expected_revision=0,
                name="Invalid child",
                kind="expense",
                parent_id=income.id,
            ),
        )


def test_category_kind_is_immutable(session: Session) -> None:
    category = create_category(session, "Food")
    with pytest.raises(service.HouseholdError, match="immutable"):
        service.save_category(
            session,
            s.CategoryWrite(expected_revision=1, name="Salary", kind="income"),
            category.id,
        )


@pytest.mark.parametrize("provider", ["gls", "ebank", "lunar"])
def test_source_provider_fixtures_have_exact_decimal_amounts_and_utc_dates(
    session: Session, synthetic_sources: dict[str, uuid.UUID], provider: str
) -> None:
    transaction, account = service.source(session, synthetic_sources[provider])
    assert account.provider == provider
    assert account.currency == "EUR"
    assert transaction.amount == Decimal("-12.34")
    expected = datetime(2026, 9, index_for_provider(provider), 12, tzinfo=UTC)
    assert transaction.ts.replace(tzinfo=UTC) == expected


def index_for_provider(provider: str) -> int:
    """Map the synthetic provider fixture to its source-calendar day."""
    return {"gls": 1, "ebank": 2, "lunar": 3}[provider]


def test_stable_confirmed_merchant_learns_consistent_human_choice(
    session: Session, synthetic_sources: dict[str, uuid.UUID]
) -> None:
    category = create_category(session, "Food")
    merchant, rule = learnable_merchant(session, synthetic_sources, category)

    assert rule.state == "active"
    assert rule.category_id == category.id
    assert rule.treatment == "expense"
    assert len(rule.evidence) == 1
    assert service.latest_rule(session, merchant) == rule


@pytest.mark.parametrize(
    ("identity_kind", "confirmed"),
    [("processor", True), ("marketplace", True), ("stable", False)],
)
def test_unstable_or_unconfirmed_identity_does_not_learn_blanket_rule(
    session: Session,
    synthetic_sources: dict[str, uuid.UUID],
    identity_kind: Literal["processor", "marketplace", "stable"],
    confirmed: bool,
) -> None:
    category = create_category(session, "Food")
    merchant = create_merchant(session, identity_kind=identity_kind, confirmed=confirmed)
    service.save_classification(
        session,
        synthetic_sources["ebank"],
        classification_body(
            category,
            Decimal("-12.34"),
            merchant_id=merchant.id,
            identity_confirmed=True,
        ),
    )
    rule = service.latest_rule(session, merchant)
    assert rule is not None
    assert rule.state == "insufficient"


def test_split_and_conflicting_confirmations_prevent_blanket_rule(
    session: Session,
    synthetic_sources: dict[str, uuid.UUID],
) -> None:
    first_category = create_category(session, "Food")
    second_category = create_category(session, "Household")
    merchant = create_merchant(session)
    split_body = s.ClassificationWrite(
        expected_revision=0,
        treatment="expense",
        merchant_id=merchant.id,
        identity_confirmed=True,
        allocations=[
            s.Split(category_id=first_category.id, amount=Decimal("-5.00")),
            s.Split(category_id=second_category.id, amount=Decimal("-7.34")),
        ],
        explanation="Synthetic split confirmation",
    )
    service.save_classification(session, synthetic_sources["gls"], split_body)
    split_rule = service.latest_rule(session, merchant)
    assert split_rule is not None
    assert split_rule.state == "conflict"

    service.save_classification(
        session,
        synthetic_sources["ebank"],
        classification_body(
            first_category,
            Decimal("-12.34"),
            merchant_id=merchant.id,
            identity_confirmed=True,
        ),
    )
    service.save_classification(
        session,
        synthetic_sources["lunar"],
        classification_body(
            second_category,
            Decimal("-12.34"),
            merchant_id=merchant.id,
            identity_confirmed=True,
        ),
    )
    conflicting_rule = service.latest_rule(session, merchant)
    assert conflicting_rule is not None
    assert conflicting_rule.state == "conflict"


def test_alias_normalization_uniqueness_correction_and_old_rule_disable(
    session: Session, synthetic_sources: dict[str, uuid.UUID]
) -> None:
    category = create_category(session, "Food")
    first, active = learnable_merchant(session, synthetic_sources, category)
    second = create_merchant(session, "Another Merchant")
    alias = service.save_alias(
        session,
        s.AliasWrite(
            expected_revision=0,
            merchant_id=first.id,
            provider="gls",
            label="  SYNTHETIC   MARKET ",
            confirmed=True,
        ),
    )
    assert alias.normalized == "synthetic market"

    with pytest.raises(service.HouseholdError, match="already exists"):
        service.save_alias(
            session,
            s.AliasWrite(
                expected_revision=0,
                merchant_id=second.id,
                provider="gls",
                label="Synthetic Market",
            ),
        )

    corrected = service.save_alias(
        session,
        s.AliasWrite(
            expected_revision=alias.revision,
            merchant_id=second.id,
            provider="gls",
            label="Synthetic Market",
            confirmed=True,
        ),
        alias.id,
    )
    assert corrected.merchant_id == second.id
    assert corrected.revision == 2
    disabled = service.latest_rule(session, first)
    assert active.state == "active"
    assert disabled is not None
    assert disabled.state == "disabled"


def test_alias_normalization_is_provider_scoped(
    session: Session,
) -> None:
    first = create_merchant(session, "First")
    second = create_merchant(session, "Second")
    gls_alias = service.save_alias(
        session,
        s.AliasWrite(
            expected_revision=0,
            merchant_id=first.id,
            provider="gls",
            label="Synthetic Coffee",
        ),
    )
    ebank_alias = service.save_alias(
        session,
        s.AliasWrite(
            expected_revision=0,
            merchant_id=second.id,
            provider="ebank",
            label="synthetic coffee",
        ),
    )
    assert gls_alias.normalized == ebank_alias.normalized


def test_manual_override_protects_assignment_and_rule_control_versions(
    session: Session, synthetic_sources: dict[str, uuid.UUID]
) -> None:
    category = create_category(session, "Food")
    merchant, rule = learnable_merchant(session, synthetic_sources, category)

    disabled = service.control_rule(
        session, rule.id, s.RuleControl(expected_version=rule.version, disabled=True)
    )
    assert disabled.state == "disabled"
    assert disabled.version == rule.version + 1
    enabled = service.control_rule(
        session,
        disabled.id,
        s.RuleControl(expected_version=disabled.version, disabled=False),
    )
    assert enabled.state == "active"
    assert enabled.version == disabled.version + 2

    with pytest.raises(service.HouseholdError, match="current rule version"):
        service.control_rule(
            session,
            disabled.id,
            s.RuleControl(expected_version=enabled.version, disabled=True),
        )

    record = service.save_classification(
        session,
        synthetic_sources["gls"],
        classification_body(
            category,
            Decimal("-12.34"),
            merchant_id=merchant.id,
        ),
    )
    assert record.provenance == "manual"
    preview = service.preview_rule(session, enabled.id, limit=10, offset=0)
    assert all(
        s.Candidate.model_validate(row).transaction_id != record.transaction_id
        for row in preview.candidates
    )


def test_explanation_retains_source_facts_and_rule_provenance(
    session: Session, synthetic_sources: dict[str, uuid.UUID]
) -> None:
    category = create_category(session, "Food")
    merchant, rule = learnable_merchant(session, synthetic_sources, category)
    alias = service.save_alias(
        session,
        s.AliasWrite(
            expected_revision=0,
            merchant_id=merchant.id,
            provider="gls",
            label="Synthetic Market",
            confirmed=True,
        ),
    )
    assert alias.confirmed
    suggestion = service.suggest(session, synthetic_sources["gls"])
    assert suggestion.rule is not None
    assert suggestion.rule.id == rule.id
    assert suggestion.source_hint == "card_payment"
    assert "exact confirmed" in suggestion.explanation
    assert "Synthetic Market" not in suggestion.explanation


@pytest.mark.parametrize(
    ("amounts", "message"),
    [
        ((Decimal("-12.33"),), "exactly conserve"),
        ((Decimal("-12.34"), Decimal("0.00")), "duplicate split category"),
        ((Decimal("12.34"),), "exactly conserve"),
    ],
)
def test_bad_splits_rejected(
    session: Session,
    synthetic_sources: dict[str, uuid.UUID],
    amounts: tuple[Decimal, ...],
    message: str,
) -> None:
    category = create_category(session, "Food")
    splits = [s.Split(category_id=category.id, amount=amount) for amount in amounts]
    if len(amounts) == 2:
        splits[1] = s.Split(category_id=category.id, amount=Decimal("-0.01"))
    body = s.ClassificationWrite(
        expected_revision=0,
        treatment="expense",
        allocations=splits,
        explanation="Invalid synthetic allocation",
    )
    with pytest.raises(service.HouseholdError, match=message):
        service.save_classification(session, synthetic_sources["gls"], body)


def test_fractional_cent_splits_are_rejected_even_when_they_conserve(
    session: Session, synthetic_sources: dict[str, uuid.UUID]
) -> None:
    groceries = create_category(session, "Groceries")
    household = create_category(session, "Household")
    body = s.ClassificationWrite(
        expected_revision=0,
        treatment="expense",
        allocations=[
            s.Split(category_id=groceries.id, amount=Decimal("-12.335")),
            s.Split(category_id=household.id, amount=Decimal("-0.005")),
        ],
        explanation="Synthetic fractional-cent allocation",
    )
    with pytest.raises(service.HouseholdError, match="exact source cents"):
        service.save_classification(session, synthetic_sources["gls"], body)


def test_wrong_split_sign_and_category_kind_are_rejected(
    session: Session, synthetic_sources: dict[str, uuid.UUID]
) -> None:
    income = create_category(session, "Income", kind="income")
    with pytest.raises(service.HouseholdError, match="wrong financial type"):
        service.save_classification(
            session,
            synthetic_sources["gls"],
            classification_body(income, Decimal("-12.34")),
        )
    expense = create_category(session, "Expense")
    with pytest.raises(service.HouseholdError, match="splits must exactly conserve"):
        service.save_classification(
            session,
            synthetic_sources["gls"],
            classification_body(expense, Decimal("12.34")),
        )


def test_opposing_split_sign_is_rejected_when_net_total_matches_source(
    session: Session, synthetic_sources: dict[str, uuid.UUID]
) -> None:
    expense = create_category(session, "Expense")
    offset = create_category(session, "Offset")
    body = s.ClassificationWrite(
        expected_revision=0,
        treatment="expense",
        allocations=[
            s.Split(category_id=expense.id, amount=Decimal("-13.00")),
            s.Split(category_id=offset.id, amount=Decimal("0.66")),
        ],
        explanation="Synthetic opposing-sign allocation",
    )
    with pytest.raises(service.HouseholdError, match="split sign must match"):
        service.save_classification(session, synthetic_sources["gls"], body)


def test_economic_split_amounts_are_signed_and_exact_for_eur_and_dkk(
    session: Session, synthetic_sources: dict[str, uuid.UUID]
) -> None:
    dkk_account_id = uuid.uuid5(uuid.NAMESPACE_URL, "synthetic-dkk-account")
    dkk_transaction_id = uuid.uuid5(uuid.NAMESPACE_URL, "synthetic-dkk-transaction")
    session.add(m.Account(id=dkk_account_id, provider="lunar", currency="DKK"))
    session.add(
        m.SourceTransaction(
            id=dkk_transaction_id,
            account_id=dkk_account_id,
            ts=datetime(2026, 9, 4, 12, tzinfo=UTC),
            amount=Decimal("100.00"),
            kind="salary",
            counterparty="Synthetic Employer",
        )
    )
    session.flush()
    income = create_category(session, "Salary", kind="income")
    result = service.save_classification(
        session,
        dkk_transaction_id,
        classification_body(income, Decimal("100.00"), treatment="income"),
    )
    assert result.source_currency == "DKK"
    assert service.classification_out(session, result).allocations[0].amount == Decimal("100.00")


def test_transfer_and_refund_links_reference_valid_opposite_bank_movements(
    session: Session, synthetic_sources: dict[str, uuid.UUID]
) -> None:
    original_id = synthetic_sources["gls"]
    transfer_id = uuid.uuid5(uuid.NAMESPACE_URL, "synthetic-transfer-leg")
    own_account_id = uuid.uuid5(uuid.NAMESPACE_URL, "synthetic-own-account")
    session.add(m.Account(id=own_account_id, provider="ebank", currency="EUR"))
    session.add(
        m.SourceTransaction(
            id=transfer_id,
            account_id=own_account_id,
            ts=datetime(2026, 9, 5, 12, tzinfo=UTC),
            amount=Decimal("12.34"),
            kind="internal_transfer",
            counterparty="Synthetic Own Account",
        )
    )
    refund_id = uuid.uuid5(uuid.NAMESPACE_URL, "synthetic-refund")
    refund_account_id = uuid.uuid5(uuid.NAMESPACE_URL, "synthetic-refund-account")
    session.add(m.Account(id=refund_account_id, provider="lunar", currency="EUR"))
    session.add(
        m.SourceTransaction(
            id=refund_id,
            account_id=refund_account_id,
            ts=datetime(2026, 9, 6, 12, tzinfo=UTC),
            amount=Decimal("12.34"),
            kind="refund",
            counterparty="Synthetic Market",
        )
    )
    session.flush()

    transfer = service.save_classification(
        session,
        original_id,
        s.ClassificationWrite(
            expected_revision=0,
            treatment="transfer",
            links=[s.ReconciliationLink(related_transaction_id=transfer_id, kind="transfer")],
            explanation="Synthetic internal transfer",
        ),
    )
    refund_category = create_category(session, "Refundable purchase")
    refund = service.save_classification(
        session,
        refund_id,
        s.ClassificationWrite(
            expected_revision=0,
            treatment="refund",
            allocations=[s.Split(category_id=refund_category.id, amount=Decimal("12.34"))],
            links=[s.ReconciliationLink(related_transaction_id=original_id, kind="refund")],
            explanation="Synthetic refund linked to debit",
        ),
    )
    assert len(service.classification_out(session, transfer).links) == 1
    assert service.classification_out(session, refund).links[0].kind == "refund"


def test_transaction_link_validation_rejects_bad_transfer_and_refund_refs(
    session: Session, synthetic_sources: dict[str, uuid.UUID]
) -> None:
    category = create_category(session, "Refunded expenses")
    refund_id = uuid.uuid5(uuid.NAMESPACE_URL, "synthetic-positive-refund")
    refund_account_id = uuid.uuid5(uuid.NAMESPACE_URL, "synthetic-positive-refund-account")
    credit_id = uuid.uuid5(uuid.NAMESPACE_URL, "synthetic-credit-reference")
    credit_account_id = uuid.uuid5(uuid.NAMESPACE_URL, "synthetic-credit-account")
    session.add(m.Account(id=refund_account_id, provider="lunar", currency="EUR"))
    session.add(m.Account(id=credit_account_id, provider="ebank", currency="EUR"))
    session.add(
        m.SourceTransaction(
            id=refund_id,
            account_id=refund_account_id,
            ts=datetime(2026, 9, 7, 12, tzinfo=UTC),
            amount=Decimal("12.34"),
            kind="refund",
            counterparty="Synthetic Market",
        )
    )
    session.add(
        m.SourceTransaction(
            id=credit_id,
            account_id=credit_account_id,
            ts=datetime(2026, 9, 8, 12, tzinfo=UTC),
            amount=Decimal("12.34"),
            kind="credit",
            counterparty="Synthetic Credit",
        )
    )
    session.flush()
    with pytest.raises(service.HouseholdError, match="opposite signs"):
        service.save_classification(
            session,
            synthetic_sources["gls"],
            s.ClassificationWrite(
                expected_revision=0,
                treatment="transfer",
                links=[
                    s.ReconciliationLink(
                        related_transaction_id=synthetic_sources["ebank"], kind="transfer"
                    )
                ],
                explanation="Invalid same-sign transfer",
            ),
        )
    with pytest.raises(service.HouseholdError, match="original debit"):
        service.save_classification(
            session,
            refund_id,
            s.ClassificationWrite(
                expected_revision=0,
                treatment="refund",
                allocations=[s.Split(category_id=category.id, amount=Decimal("12.34"))],
                links=[s.ReconciliationLink(related_transaction_id=credit_id, kind="refund")],
                explanation="Invalid refund reference",
            ),
        )


def test_audit_and_revision_are_atomic_and_stale_writes_conflict(
    session: Session, synthetic_sources: dict[str, uuid.UUID]
) -> None:
    category = create_category(session, "Food")
    transaction_id = synthetic_sources["gls"]
    saved = service.save_classification(
        session, transaction_id, classification_body(category, Decimal("-12.34"))
    )
    assert (
        session.scalar(
            select(func.count()).select_from(m.Audit).where(m.Audit.subject_id == transaction_id)
        )
        == 1
    )

    with pytest.raises(service.HouseholdError, match="revision conflict"):
        service.save_classification(
            session,
            transaction_id,
            classification_body(category, Decimal("-12.34"), revision=0),
        )
    assert saved.revision == 1
    assert (
        session.scalar(
            select(func.count()).select_from(m.Audit).where(m.Audit.subject_id == transaction_id)
        )
        == 1
    )

    session.rollback()
    assert session.get(m.Classification, transaction_id) is None
    assert (
        session.scalar(
            select(func.count()).select_from(m.Audit).where(m.Audit.subject_id == transaction_id)
        )
        == 0
    )


def test_undo_restores_prior_classification_as_a_new_manual_revision(
    session: Session, synthetic_sources: dict[str, uuid.UUID]
) -> None:
    category = create_category(session, "Food")
    transaction_id = synthetic_sources["gls"]
    first = service.save_classification(
        session, transaction_id, classification_body(category, Decimal("-12.34"))
    )
    original_event = session.scalar(
        select(m.Audit).where(
            m.Audit.subject_type == "classification",
            m.Audit.subject_id == transaction_id,
        )
    )
    assert original_event is not None
    corrected = service.save_classification(
        session,
        transaction_id,
        classification_body(
            category,
            Decimal("-12.34"),
            revision=first.revision,
            explanation="Second synthetic explanation",
        ),
    )
    correction_event = session.scalar(
        select(m.Audit)
        .where(
            m.Audit.subject_type == "classification",
            m.Audit.subject_id == transaction_id,
            m.Audit.action == "save",
        )
        .order_by(m.Audit.created_at.desc(), m.Audit.id.desc())
    )
    assert correction_event is not None

    undone = service.undo_classification(
        session,
        transaction_id,
        s.Undo(expected_revision=corrected.revision, audit_id=correction_event.id),
    )
    assert undone.revision == 3
    assert undone.provenance == "manual"
    assert undone.explanation == f"undo audit {correction_event.id}"
    assert original_event.before is None


def test_source_resync_flags_drift_but_retains_manual_allocations(
    session: Session, synthetic_sources: dict[str, uuid.UUID]
) -> None:
    category = create_category(session, "Food")
    transaction_id = synthetic_sources["gls"]
    record = service.save_classification(
        session, transaction_id, classification_body(category, Decimal("-12.34"))
    )
    transaction = session.get(m.SourceTransaction, transaction_id)
    assert transaction is not None
    transaction.amount = Decimal("-14.00")
    transaction.ts = datetime(2026, 9, 9, 12, tzinfo=UTC)
    transaction.counterparty = "Synthetic Updated Market"
    session.flush()

    result = service.classification_out(session, record)
    assert result.source_changed
    assert result.source_amount == Decimal("-12.34")
    assert result.allocations[0].amount == Decimal("-12.34")


def test_preview_is_persisted_without_writes_then_applies_only_on_approval(
    session: Session,
    synthetic_sources: dict[str, uuid.UUID],
) -> None:
    category = create_category(session, "Food")
    merchant, rule = learnable_merchant(session, synthetic_sources, category)
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

    preview = service.preview_rule(session, rule.id, limit=20, offset=0)
    assert preview.id is not None
    assert not preview.applied
    assert session.get(m.Classification, synthetic_sources["gls"]) is None
    assert session.get(m.Preview, preview.id) is preview
    assert any(
        s.Candidate.model_validate(candidate).transaction_id == synthetic_sources["gls"]
        for candidate in preview.candidates
    )

    applied = service.apply_preview(session, preview.id)
    record = session.get(m.Classification, synthetic_sources["gls"])
    assert applied.applied
    assert record is not None
    assert record.provenance == "rule"
    assert record.rule_id == rule.id
    assert record.merchant_id == merchant.id
    assert service.classification_out(session, record).allocations[0].category_id == category.id


@pytest.mark.parametrize("stale_surface", ["source", "alias", "rule", "classification"])
def test_preview_apply_rejects_stale_source_alias_rule_and_classification(
    session: Session,
    synthetic_sources: dict[str, uuid.UUID],
    stale_surface: str,
) -> None:
    category = create_category(session, "Food")
    merchant, rule = learnable_merchant(session, synthetic_sources, category)
    alias = service.save_alias(
        session,
        s.AliasWrite(
            expected_revision=0,
            merchant_id=merchant.id,
            provider="gls",
            label="Synthetic Market",
            confirmed=True,
        ),
    )
    preview = service.preview_rule(session, rule.id, limit=20, offset=0)
    if stale_surface == "source":
        transaction = session.get(m.SourceTransaction, synthetic_sources["gls"])
        assert transaction is not None
        transaction.amount = Decimal("-13.00")
        session.flush()
    elif stale_surface == "alias":
        service.save_alias(
            session,
            s.AliasWrite(
                expected_revision=alias.revision,
                merchant_id=merchant.id,
                provider="gls",
                label="Synthetic Market Corrected",
                confirmed=True,
            ),
            alias.id,
        )
    elif stale_surface == "rule":
        service.control_rule(
            session, rule.id, s.RuleControl(expected_version=rule.version, disabled=True)
        )
    else:
        service.save_classification(
            session,
            synthetic_sources["gls"],
            classification_body(category, Decimal("-12.34")),
        )

    with pytest.raises(
        service.HouseholdError,
        match=r"stale|no longer active|revision conflict",
    ):
        service.apply_preview(session, preview.id)


def test_preview_excludes_manual_classifications(
    session: Session,
    synthetic_sources: dict[str, uuid.UUID],
) -> None:
    category = create_category(session, "Food")
    merchant, rule = learnable_merchant(session, synthetic_sources, category)
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
        synthetic_sources["gls"],
        classification_body(category, Decimal("-12.34")),
    )
    preview = service.preview_rule(session, rule.id, limit=20, offset=0)
    assert all(
        s.Candidate.model_validate(candidate).transaction_id != synthetic_sources["gls"]
        for candidate in preview.candidates
    )


def payment_detail_body(
    external_id: str,
    *,
    amount: Decimal = Decimal("-12.34"),
    currency: str = "EUR",
    event_kind: Literal["purchase", "refund", "funding", "unknown"] = "purchase",
) -> s.PaymentDetailWrite:
    """Return a synthetic provider detail record with stable source identity."""
    return s.PaymentDetailWrite(
        provider="paypal",
        source_account_id="synthetic-wallet",
        external_id=external_id,
        ts=datetime(2026, 9, 10, 12, tzinfo=UTC),
        amount=amount,
        currency=currency,
        merchant_name="Synthetic Shop",
        reference="synthetic-reference",
        event_kind=event_kind,
        source_fields=s.PaymentSourceFields(transaction_id="synthetic-provider-txn"),
    )


def test_payment_detail_upsert_is_idempotent_for_detail_only_imports(
    session: Session, synthetic_sources: dict[str, uuid.UUID]
) -> None:
    first = service.upsert_payment_detail(session, payment_detail_body("detail-1"))
    second = service.upsert_payment_detail(session, payment_detail_body("detail-1"))
    foreign_currency = service.upsert_payment_detail(
        session,
        payment_detail_body(
            "detail-dkk",
            amount=Decimal("-150.00"),
            currency="DKK",
        ),
    )
    assert first.id == second.id
    assert first.revision == second.revision == 1
    assert foreign_currency.currency == "DKK"
    assert session.scalar(select(func.count()).select_from(m.Account)) == 3
    assert session.scalar(select(func.count()).select_from(m.SourceTransaction)) == 3
    assert all(session.get(m.Classification, key) is None for key in synthetic_sources.values())


def test_payment_detail_timestamp_comparison_normalizes_naive_utc() -> None:
    naive = datetime(2026, 9, 10, 12)
    aware = datetime(2026, 9, 10, 12, tzinfo=UTC)

    assert service._same_instant(naive, aware)


def test_payment_detail_upsert_is_idempotent_across_fresh_sessions(
    engine: Engine,
    session: Session,
    synthetic_sources: dict[str, uuid.UUID],
) -> None:
    body = payment_detail_body("detail-fresh-session")
    category = create_category(session, "Fresh-session purchase")
    first = service.upsert_payment_detail(session, body)
    bank_id = synthetic_sources["gls"]
    classification = service.save_classification(
        session,
        bank_id,
        s.ClassificationWrite(
            expected_revision=0,
            treatment="expense",
            allocations=[s.Split(category_id=category.id, amount=Decimal("-12.34"))],
            detail_links=[
                s.PaymentDetailLink(
                    detail_id=first.id,
                    detail_revision=first.revision,
                    bank_amount=Decimal("-12.34"),
                )
            ],
            explanation="Synthetic fresh-session link",
        ),
    )
    detail_id = first.id
    classification_revision = classification.revision
    session.commit()
    session.close()

    with Session(engine) as second_session, second_session.begin():
        second = service.upsert_payment_detail(second_session, body)
        assert second.id == detail_id
        assert second.revision == 1
        persisted = service.require(second_session, m.Classification, bank_id)
        assert persisted.revision == classification_revision
        assert not service.classification_out(second_session, persisted).detail_changed


def test_changed_payment_detail_revision_invalidates_bank_link(
    session: Session, synthetic_sources: dict[str, uuid.UUID]
) -> None:
    category = create_category(session, "Online purchases")
    detail = service.upsert_payment_detail(session, payment_detail_body("detail-2"))
    bank_id = synthetic_sources["gls"]
    classification = s.ClassificationWrite(
        expected_revision=0,
        treatment="expense",
        allocations=[s.Split(category_id=category.id, amount=Decimal("-12.34"))],
        detail_links=[
            s.PaymentDetailLink(
                detail_id=detail.id,
                detail_revision=detail.revision,
                bank_amount=Decimal("-12.34"),
            )
        ],
        explanation="Synthetic bank-to-wallet reconciliation",
    )
    saved = service.save_classification(session, bank_id, classification)
    assert not service.classification_out(session, saved).detail_changed

    changed = service.upsert_payment_detail(
        session, payment_detail_body("detail-2", amount=Decimal("-15.00"))
    )
    assert changed.revision == 2
    assert service.classification_out(session, saved).detail_changed
    transaction = session.get(m.SourceTransaction, bank_id)
    assert transaction is not None
    assert transaction.amount == Decimal("-12.34")


@pytest.mark.parametrize(
    ("link_amount", "event_kind", "message"),
    [
        (Decimal("-10.00"), "purchase", "conserve"),
        (Decimal("-12.34"), "funding", "funding"),
    ],
)
def test_invalid_payment_detail_links_are_rejected(
    session: Session,
    synthetic_sources: dict[str, uuid.UUID],
    link_amount: Decimal,
    event_kind: Literal["purchase", "funding"],
    message: str,
) -> None:
    category = create_category(session, "Online purchases")
    detail = service.upsert_payment_detail(
        session,
        payment_detail_body("invalid-detail", event_kind=event_kind),
    )
    bank_amount = Decimal("-12.34")
    body = s.ClassificationWrite(
        expected_revision=0,
        treatment="expense",
        allocations=[s.Split(category_id=category.id, amount=bank_amount)],
        detail_links=[
            s.PaymentDetailLink(
                detail_id=detail.id,
                detail_revision=detail.revision,
                bank_amount=link_amount,
            )
        ],
        explanation="Invalid synthetic enrichment",
    )
    with pytest.raises(service.HouseholdError, match=message):
        service.save_classification(session, synthetic_sources["gls"], body)


def test_classification_rejects_non_bank_provider_and_unconfirmed_identity(
    session: Session, synthetic_sources: dict[str, uuid.UUID]
) -> None:
    account_id = uuid.uuid5(uuid.NAMESPACE_URL, "synthetic-investment-account")
    transaction_id = uuid.uuid5(uuid.NAMESPACE_URL, "synthetic-investment-transaction")
    session.add(m.Account(id=account_id, provider="nordnet", currency="EUR"))
    session.add(
        m.SourceTransaction(
            id=transaction_id,
            account_id=account_id,
            ts=datetime(2026, 9, 11, 12, tzinfo=UTC),
            amount=Decimal("-1.00"),
            kind="investment",
            counterparty="Synthetic Fund",
        )
    )
    session.flush()
    category = create_category(session, "Investments")
    with pytest.raises(service.HouseholdError, match="bank movement"):
        service.save_classification(
            session, transaction_id, classification_body(category, Decimal("-1.00"))
        )

    transaction, account = service.source(session, synthetic_sources["gls"])
    assert transaction is not None
    assert account is not None
    with pytest.raises(service.HouseholdError, match="requires a merchant"):
        service.validate_splits(
            session,
            transaction,
            account,
            s.ClassificationWrite(
                expected_revision=0,
                treatment="expense",
                identity_confirmed=True,
                allocations=[s.Split(category_id=category.id, amount=Decimal("-12.34"))],
                explanation="Invalid identity confirmation",
            ),
            None,
        )
