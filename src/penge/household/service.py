"""Transactional household operations.

Callers own the database transaction and the shared refresh write intent.
Postgres advisory locking serializes the small household correction surface,
including rule learning and absent-row creation; source facts are row-locked.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from penge.household import models as m
from penge.household import schemas as s

BANK_PROVIDERS = ("gls", "ebank", "lunar")


class HouseholdError(ValueError):
    """Explicit domain error safe for the household correction interface."""

    def __init__(self, message: str, *, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def lock_household(session: Session) -> None:
    """Serialize correction/rule changes across API and worker processes."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(select(func.pg_advisory_xact_lock(330)))


def require[Model: m.Base](session: Session, model: type[Model], key: uuid.UUID) -> Model:
    """Read and lock an existing domain object or reject explicitly."""
    result = session.get(model, key, with_for_update=True, populate_existing=True)
    if result is None:
        raise HouseholdError(f"{model.__name__} not found", status=404)
    return result


def check_revision(actual: int, expected: int) -> None:
    """Never silently overwrite a concurrent human correction."""
    if actual != expected:
        raise HouseholdError("revision conflict; reload and review the latest state", status=409)


def normalize_label(label: str) -> str:
    """Exact identity key: Unicode case folding and whitespace, not fuzzy matching."""
    return " ".join(label.casefold().split())


def _same_instant(left: datetime, right: datetime) -> bool:
    """Compare UTC instants across databases that return naive timestamps."""
    normalized = tuple(
        value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        for value in (left, right)
    )
    return normalized[0] == normalized[1]


def processor_only_label(label: str) -> bool:
    """A payment processor's generic banking label is not a merchant identity."""
    words = set(re.findall(r"[a-z]+", normalize_label(label)))
    return "paypal" in words and words <= {
        "paypal",
        "europe",
        "s",
        "a",
        "r",
        "l",
        "et",
        "cie",
        "sca",
        "c",
        "payment",
        "payments",
    }


def audit(
    session: Session,
    subject_type: str,
    subject_id: uuid.UUID,
    action: str,
    before: dict[str, object] | None,
    after: dict[str, object],
) -> None:
    """Append a minimal snapshot inside the same transaction as the correction."""
    session.add(
        m.Audit(
            subject_type=subject_type,
            subject_id=subject_id,
            action=action,
            before=before,
            after=after,
            actor="household",
        )
    )


def save_category(
    session: Session, body: s.CategoryWrite, key: uuid.UUID | None = None
) -> m.Category:
    """Create or revise a stable category; kind is immutable after creation."""
    lock_household(session)
    category = require(session, m.Category, key) if key else None
    check_revision(category.revision if category else 0, body.expected_revision)
    before = s.CategoryOut.model_validate(category).model_dump(mode="json") if category else None
    if category and category.kind != body.kind:
        raise HouseholdError("category kind is immutable; create a new category")
    if not body.name.strip():
        raise HouseholdError("category name cannot be blank")
    parent_id = body.parent_id
    seen = {key} if key else set()
    while parent_id:
        if parent_id in seen:
            raise HouseholdError("category cycle")
        seen.add(parent_id)
        parent = require(session, m.Category, parent_id)
        if parent.kind != body.kind:
            raise HouseholdError("parent category must have the same financial type")
        parent_id = parent.parent_id
    if category is None:
        category = m.Category(id=uuid.uuid4(), revision=0)
        session.add(category)
    category.name = body.name.strip()
    category.kind = body.kind
    category.parent_id = body.parent_id
    category.sort_order = body.sort_order
    category.archived = body.archived
    category.revision += 1
    session.flush()
    audit(
        session,
        "category",
        category.id,
        "save",
        before,
        s.CategoryOut.model_validate(category).model_dump(mode="json"),
    )
    return category


def save_merchant(
    session: Session, body: s.MerchantWrite, key: uuid.UUID | None = None
) -> m.Merchant:
    """Local decisions never inherit public-reference category hints."""
    lock_household(session)
    merchant = require(session, m.Merchant, key) if key else None
    check_revision(merchant.revision if merchant else 0, body.expected_revision)
    before = s.MerchantOut.model_validate(merchant).model_dump(mode="json") if merchant else None
    if not body.name.strip():
        raise HouseholdError("merchant name cannot be blank")
    if merchant is None:
        merchant = m.Merchant(id=uuid.uuid4(), revision=0, rule_version=0)
        session.add(merchant)
    for field, value in body.model_dump(exclude={"expected_revision"}).items():
        setattr(merchant, field, value)
    merchant.name = body.name.strip()
    merchant.revision += 1
    session.flush()
    audit(
        session,
        "merchant",
        merchant.id,
        "save",
        before,
        s.MerchantOut.model_validate(merchant).model_dump(mode="json"),
    )
    learn(session, merchant.id)
    return merchant


def save_alias(session: Session, body: s.AliasWrite, key: uuid.UUID | None = None) -> m.Alias:
    """Explicit provider-scoped identity confirmation/correction."""
    lock_household(session)
    require(session, m.Merchant, body.merchant_id)
    alias = require(session, m.Alias, key) if key else None
    check_revision(alias.revision if alias else 0, body.expected_revision)
    before = s.AliasOut.model_validate(alias).model_dump(mode="json") if alias else None
    normalized = normalize_label(body.label)
    if not normalized or not body.provider.strip():
        raise HouseholdError("alias label and provider cannot be blank")
    if body.confirmed and processor_only_label(body.label):
        raise HouseholdError("processor-only PayPal label cannot confirm a merchant identity")
    duplicate = session.scalar(
        select(m.Alias).where(m.Alias.provider == body.provider, m.Alias.normalized == normalized)
    )
    if duplicate and (alias is None or duplicate.id != alias.id):
        raise HouseholdError("provider alias already exists; correct it by revision", status=409)
    old_merchant = alias.merchant_id if alias else None
    if alias is None:
        alias = m.Alias(id=uuid.uuid4(), revision=0)
        session.add(alias)
    alias.merchant_id = body.merchant_id
    alias.provider = body.provider
    alias.normalized = normalized
    alias.confirmed = body.confirmed
    alias.revision += 1
    session.flush()
    audit(
        session,
        "alias",
        alias.id,
        "save",
        before,
        s.AliasOut.model_validate(alias).model_dump(mode="json"),
    )
    if old_merchant and old_merchant != alias.merchant_id:
        disable_rule(session, old_merchant, "alias identity corrected; review previous assignments")
    return alias


def source(session: Session, key: uuid.UUID) -> tuple[m.SourceTransaction, m.Account]:
    """Authoritative source amount/currency/date, never a PayPal gross substitution."""
    transaction = require(session, m.SourceTransaction, key)
    return transaction, require(session, m.Account, transaction.account_id)


def classification_out(session: Session, record: m.Classification) -> s.ClassificationOut:
    """Explain the effective correction and any resync/enrichment drift."""
    splits = session.scalars(
        select(m.Allocation)
        .where(m.Allocation.transaction_id == record.transaction_id)
        .order_by(m.Allocation.category_id)
    ).all()
    links = session.scalars(
        select(m.Link)
        .where(m.Link.transaction_id == record.transaction_id)
        .order_by(m.Link.related_transaction_id, m.Link.kind)
    ).all()
    details = session.scalars(
        select(m.DetailLink)
        .where(m.DetailLink.transaction_id == record.transaction_id)
        .order_by(m.DetailLink.detail_id)
    ).all()
    transaction, account = source(session, record.transaction_id)
    stale = any(
        require(session, m.PaymentDetail, link.detail_id).revision != link.detail_revision
        for link in details
    )
    source_changed = (
        record.source_amount != transaction.amount
        or record.source_currency != account.currency
        or record.source_ts != transaction.ts
        or record.source_counterparty != transaction.counterparty
        or record.source_kind != transaction.kind
    )
    return s.ClassificationOut(
        **{
            field: getattr(record, field)
            for field in s.ClassificationOut.model_fields
            if field
            not in {
                "allocations",
                "links",
                "detail_links",
                "source_changed",
                "detail_changed",
                "review_state",
            }
        },
        allocations=[s.Split.model_validate(row) for row in splits],
        links=[
            s.ReconciliationLink.model_validate(
                {
                    "related_transaction_id": row.related_transaction_id,
                    "kind": row.kind,
                }
            )
            for row in links
        ],
        detail_links=[s.PaymentDetailLink.model_validate(row) for row in details],
        review_state="needs_review" if source_changed or stale else record.review_state,
        source_changed=source_changed,
        detail_changed=stale,
    )


def validate_splits(
    session: Session,
    transaction: m.SourceTransaction,
    account: m.Account,
    body: s.ClassificationWrite,
    old: s.ClassificationOut | None,
) -> None:
    """Conserve exact signed source cents and validate financial category types."""
    if account.provider not in BANK_PROVIDERS:
        raise HouseholdError("household classifications currently require a bank movement")
    if account.currency not in ("EUR", "DKK"):
        raise HouseholdError("unsupported source currency precision; review required")
    money = [split.amount for split in body.allocations]
    ids = [split.category_id for split in body.allocations]
    if len(ids) != len(set(ids)):
        raise HouseholdError("duplicate split category")
    economic = body.treatment in ("expense", "income", "refund")
    if economic:
        validate_economic_splits(session, transaction, body, old)
    elif money:
        raise HouseholdError("transfer/excluded/unclassified treatments cannot have allocations")
    if body.identity_confirmed and body.merchant_id is None:
        raise HouseholdError("identity confirmation requires a merchant")
    if body.merchant_id:
        merchant = require(session, m.Merchant, body.merchant_id)
        if merchant.archived:
            raise HouseholdError("archived merchant cannot receive a new confirmation")


def validate_economic_splits(
    session: Session,
    transaction: m.SourceTransaction,
    body: s.ClassificationWrite,
    old: s.ClassificationOut | None,
) -> None:
    """Validate conservation, source precision/sign and retained category lifecycle."""
    money = [split.amount for split in body.allocations]
    if not money or sum(money, Decimal(0)) != transaction.amount:
        raise HouseholdError("splits must exactly conserve the signed source amount")
    if transaction.amount == 0:
        raise HouseholdError("zero movement cannot be income or spending")
    for amount in [transaction.amount, *money]:
        if amount != amount.quantize(Decimal("0.01")):
            raise HouseholdError("EUR/DKK allocations must use exact source cents")
        if amount == 0 or (amount > 0) != (transaction.amount > 0):
            raise HouseholdError("split sign must match the source movement")
    if (body.treatment == "expense") != (transaction.amount < 0):
        raise HouseholdError("expense must be debit; income/refund must be credit")
    for split in body.allocations:
        category = require(session, m.Category, split.category_id)
        kind = "income" if body.treatment == "income" else "expense"
        if category.kind != kind:
            raise HouseholdError("allocation category has the wrong financial type")
        retained = old and any(x.category_id == category.id for x in old.allocations)
        if category.archived and not retained:
            raise HouseholdError("archived category cannot receive a new assignment")


def validate_links(
    session: Session,
    transaction: m.SourceTransaction,
    account: m.Account,
    body: s.ClassificationWrite,
) -> None:
    """References are explicit; ambiguous matching never creates another expense."""
    keys = [(link.related_transaction_id, link.kind) for link in body.links]
    if len(keys) != len(set(keys)):
        raise HouseholdError("duplicate reconciliation reference")
    for link in body.links:
        if link.related_transaction_id == transaction.id:
            raise HouseholdError("transaction cannot reference itself")
        other, other_account = source(session, link.related_transaction_id)
        if link.kind == "transfer":
            if body.treatment != "transfer" or other_account.id == account.id:
                raise HouseholdError("transfer must link distinct own accounts")
            if (other.amount > 0) == (transaction.amount > 0):
                raise HouseholdError("transfer legs must have opposite signs")
        elif body.treatment != "refund" or other.amount >= 0:
            raise HouseholdError("refund must reference an original debit")
    validate_detail_links(session, transaction, body)


def validate_detail_links(
    session: Session,
    transaction: m.SourceTransaction,
    body: s.ClassificationWrite,
) -> None:
    """Preserve original gross currencies while reconciling signed bank allocations."""
    detail_ids = [link.detail_id for link in body.detail_links]
    if len(detail_ids) != len(set(detail_ids)):
        raise HouseholdError("duplicate payment detail")
    if body.detail_links:
        if sum((x.bank_amount for x in body.detail_links), Decimal(0)) != transaction.amount:
            raise HouseholdError("detail allocations must exactly conserve the signed bank amount")
        for link in body.detail_links:
            detail = require(session, m.PaymentDetail, link.detail_id)
            check_revision(detail.revision, link.detail_revision)
            if detail.event_kind == "funding":
                raise HouseholdError("wallet funding is not purchase/refund enrichment")
            if link.bank_amount != link.bank_amount.quantize(Decimal("0.01")):
                raise HouseholdError("detail allocation must use exact bank currency cents")
            if link.bank_amount == 0 or (link.bank_amount > 0) != (transaction.amount > 0):
                raise HouseholdError("detail allocation sign must match the bank movement")


def save_classification(
    session: Session,
    key: uuid.UUID,
    body: s.ClassificationWrite,
    *,
    rule: m.Rule | None = None,
    action: str = "save",
) -> m.Classification:
    """Atomic correction/allocation/link/audit/learning operation."""
    lock_household(session)
    transaction, account = source(session, key)
    record = session.get(m.Classification, key, with_for_update=True)
    check_revision(record.revision if record else 0, body.expected_revision)
    old = classification_out(session, record) if record else None
    if rule and record and record.provenance == "manual":
        raise HouseholdError("manual override is protected", status=409)
    validate_splits(session, transaction, account, body, old)
    validate_links(session, transaction, account, body)
    old_merchant = record.merchant_id if record else None
    if record is None:
        record = m.Classification(transaction_id=key, revision=0)
        session.add(record)
    record.treatment = body.treatment
    record.review_state = "unclassified" if body.treatment == "unclassified" else "classified"
    record.merchant_id = body.merchant_id
    record.identity_confirmed = body.identity_confirmed
    record.provenance = "rule" if rule else "manual"
    record.rule_id = rule.id if rule else None
    record.revision += 1
    record.source_amount = transaction.amount
    record.source_currency = account.currency
    record.source_ts = transaction.ts
    record.source_counterparty = transaction.counterparty
    record.source_kind = transaction.kind
    record.explanation = body.explanation
    session.flush()
    for model in (m.Allocation, m.Link, m.DetailLink):
        session.execute(delete(model).where(model.transaction_id == key))
    session.add_all(
        [
            m.Allocation(transaction_id=key, category_id=x.category_id, amount=x.amount)
            for x in body.allocations
        ]
    )
    session.add_all(
        [
            m.Link(transaction_id=key, related_transaction_id=x.related_transaction_id, kind=x.kind)
            for x in body.links
        ]
    )
    session.add_all([m.DetailLink(transaction_id=key, **x.model_dump()) for x in body.detail_links])
    session.flush()
    after = classification_out(session, record).model_dump(mode="json")
    audit(
        session, "classification", key, action, old.model_dump(mode="json") if old else None, after
    )
    session.flush()
    if rule is None:
        for merchant_id in {old_merchant, body.merchant_id} - {None}:
            if merchant_id is not None:
                learn(session, merchant_id)
    return record


def latest_rule(session: Session, merchant: m.Merchant) -> m.Rule | None:
    """Return the current version, never an older still-active version."""
    return session.scalar(
        select(m.Rule).where(
            m.Rule.merchant_id == merchant.id, m.Rule.version == merchant.rule_version
        )
    )


def new_rule(
    session: Session,
    merchant: m.Merchant,
    *,
    state: str,
    category_id: uuid.UUID | None,
    treatment: str | None,
    explanation: str,
    evidence: list[dict[str, object]],
) -> m.Rule:
    """Append a rule version; earlier explanations remain reproducible."""
    merchant.rule_version += 1
    result = m.Rule(
        merchant_id=merchant.id,
        version=merchant.rule_version,
        state=state,
        category_id=category_id,
        treatment=treatment,
        explanation=explanation,
        evidence=evidence,
    )
    session.add(result)
    session.flush()
    audit(
        session,
        "rule",
        result.id,
        "version",
        None,
        s.RuleOut.model_validate(result).model_dump(mode="json"),
    )
    if state != "active":
        records = session.scalars(
            select(m.Classification)
            .where(
                m.Classification.merchant_id == merchant.id,
                m.Classification.provenance == "rule",
                m.Classification.review_state != "needs_review",
            )
            .execution_options(yield_per=100)
        )
        for record in records:
            before = classification_out(session, record).model_dump(mode="json")
            record.review_state = "needs_review"
            record.revision += 1
            session.flush()
            audit(
                session,
                "classification",
                record.transaction_id,
                "rule_review",
                before,
                classification_out(session, record).model_dump(mode="json"),
            )
    return result


def learn(session: Session, merchant_id: uuid.UUID) -> m.Rule:
    """Conservative deterministic learning from audited human confirmations.

    Contradictory corrections remain evidence even if the current row changes.
    Split/mixed spending and refund/transfer confirmations never establish a
    blanket category. Disabled rules remain disabled until explicit review.
    """
    merchant = require(session, m.Merchant, merchant_id)
    previous = latest_rule(session, merchant)
    evidence: list[dict[str, object]] = []
    choices: set[tuple[uuid.UUID, str]] = set()
    ambiguous = False
    events = session.scalars(
        select(m.Audit)
        .where(
            m.Audit.subject_type == "classification",
            m.Audit.after["merchant_id"].as_string() == str(merchant_id),
        )
        .order_by(m.Audit.created_at, m.Audit.id)
        .execution_options(yield_per=100)
    )
    for event in events:
        out = s.ClassificationOut.model_validate(event.after)
        if (
            out.provenance != "manual"
            or out.merchant_id != merchant_id
            or not out.identity_confirmed
        ):
            continue
        evidence.append(
            {
                "audit_id": str(event.id),
                "transaction_id": str(out.transaction_id),
                "revision": out.revision,
            }
        )
        if (
            len(out.allocations) != 1
            or out.treatment not in ("expense", "income")
            or processor_only_label(out.source_counterparty or "")
        ):
            ambiguous = True
        else:
            choices.add((out.allocations[0].category_id, out.treatment))
    state = "insufficient"
    explanation = "requires confirmed stable identity and unambiguous human evidence"
    category_id = None
    treatment = None
    if previous and previous.state == "disabled":
        state, explanation = "disabled", previous.explanation
    elif ambiguous or len(choices) > 1:
        state, explanation = (
            "conflict",
            "conflicting corrections or mixed/split spending; review required",
        )
    elif (
        merchant.confirmed
        and merchant.identity_kind == "stable"
        and not merchant.archived
        and choices
        and not processor_only_label(merchant.name)
    ):
        category_id, treatment = next(iter(choices))
        state, explanation = (
            "active",
            "exact confirmed merchant identity; consistent human category evidence",
        )
    if previous and (
        previous.state,
        previous.category_id,
        previous.treatment,
        previous.evidence,
        previous.explanation,
    ) == (state, category_id, treatment, evidence, explanation):
        return previous
    return new_rule(
        session,
        merchant,
        state=state,
        category_id=category_id,
        treatment=treatment,
        explanation=explanation,
        evidence=evidence,
    )


def disable_rule(session: Session, merchant_id: uuid.UUID, explanation: str) -> m.Rule:
    """Disable without deleting history or silently reverting classified rows."""
    merchant = require(session, m.Merchant, merchant_id)
    previous = latest_rule(session, merchant)
    return new_rule(
        session,
        merchant,
        state="disabled",
        category_id=None,
        treatment=None,
        explanation=explanation,
        evidence=previous.evidence if previous else [],
    )


def control_rule(session: Session, key: uuid.UUID, body: s.RuleControl) -> m.Rule:
    """Disable or explicitly re-evaluate the latest rule; conflicts cannot be forced active."""
    lock_household(session)
    rule = require(session, m.Rule, key)
    merchant = require(session, m.Merchant, rule.merchant_id)
    check_revision(merchant.rule_version, body.expected_version)
    if rule.version != merchant.rule_version:
        raise HouseholdError("only the current rule version can be controlled", status=409)
    if body.disabled:
        return disable_rule(session, merchant.id, "explicitly disabled by household")
    new_rule(
        session,
        merchant,
        state="insufficient",
        category_id=None,
        treatment=None,
        explanation="explicit learning re-evaluation",
        evidence=rule.evidence,
    )
    return learn(session, merchant.id)


def suggest(session: Session, key: uuid.UUID) -> s.Suggestion:
    """Exact local alias/rule match; source kind is an explanation hint only."""
    transaction, account = source(session, key)
    alias = session.scalar(
        select(m.Alias).where(
            m.Alias.provider == account.provider,
            m.Alias.normalized == normalize_label(transaction.counterparty or ""),
        )
    )
    rule = None
    merchant = require(session, m.Merchant, alias.merchant_id) if alias else None
    if alias and alias.confirmed and merchant:
        rule = latest_rule(session, merchant)
    return s.Suggestion(
        transaction_id=key,
        merchant_id=merchant.id if merchant else None,
        rule=s.RuleOut.model_validate(rule) if rule else None,
        explanation=rule.explanation if rule else "no confirmed deterministic merchant rule",
        source_hint=transaction.kind,
    )


def eligible_candidate(session: Session, rule: m.Rule, key: uuid.UUID) -> s.Candidate | None:
    """One safe candidate; manual decisions and reconciliation are never overwritten."""
    transaction, account = source(session, key)
    record = session.get(m.Classification, key)
    if account.provider not in BANK_PROVIDERS or account.currency not in ("EUR", "DKK"):
        return None
    if record and (record.provenance == "manual" or record.rule_id == rule.id):
        return None
    if record and (
        session.scalar(select(m.Link).where(m.Link.transaction_id == key).limit(1))
        or session.scalar(select(m.DetailLink).where(m.DetailLink.transaction_id == key).limit(1))
    ):
        return None
    if (
        transaction.amount == 0
        or (rule.treatment == "expense") != (transaction.amount < 0)
        or transaction.amount != transaction.amount.quantize(Decimal("0.01"))
    ):
        return None
    suggestion = suggest(session, key)
    if suggestion.rule is None or suggestion.rule.id != rule.id:
        return None
    alias = session.scalar(
        select(m.Alias).where(
            m.Alias.provider == account.provider,
            m.Alias.normalized == normalize_label(transaction.counterparty or ""),
        )
    )
    return s.Candidate(
        transaction_id=key,
        expected_revision=record.revision if record else 0,
        source_amount=transaction.amount,
        source_currency=account.currency,
        source_ts=transaction.ts,
        source_kind=transaction.kind,
        source_counterparty=transaction.counterparty,
        provider=account.provider,
        normalized_counterparty=normalize_label(transaction.counterparty or ""),
        alias_id=alias.id if alias else None,
        alias_revision=alias.revision if alias else None,
    )


def preview_rule(session: Session, key: uuid.UUID, limit: int, offset: int) -> m.Preview:
    """Persist a bounded preview; creation makes no transaction assignments."""
    lock_household(session)
    rule = require(session, m.Rule, key)
    merchant = require(session, m.Merchant, rule.merchant_id)
    category = require(session, m.Category, rule.category_id) if rule.category_id else None
    if (
        rule.state != "active"
        or rule.version != merchant.rule_version
        or not category
        or category.archived
    ):
        raise HouseholdError("preview requires a current active rule and non-archived category")
    ids = session.scalars(
        select(m.SourceTransaction.id)
        .order_by(m.SourceTransaction.ts, m.SourceTransaction.id)
        .limit(limit)
        .offset(offset)
    ).all()
    candidates = [
        candidate.model_dump(mode="json")
        for key in ids
        if (candidate := eligible_candidate(session, rule, key)) is not None
    ]
    preview = m.Preview(rule_id=rule.id, candidates=candidates)
    session.add(preview)
    session.flush()
    audit(
        session,
        "preview",
        preview.id,
        "preview",
        None,
        s.PreviewOut.model_validate(preview).model_dump(mode="json"),
    )
    return preview


def apply_preview(session: Session, key: uuid.UUID) -> m.Preview:
    """All-or-nothing approval with source, alias, rule and edit revision checks."""
    lock_household(session)
    preview = require(session, m.Preview, key)
    if preview.applied:
        raise HouseholdError("preview already applied", status=409)
    rule = require(session, m.Rule, preview.rule_id)
    merchant = require(session, m.Merchant, rule.merchant_id)
    check_revision(merchant.rule_version, rule.version)
    if rule.state != "active" or rule.category_id is None:
        raise HouseholdError("rule is no longer active", status=409)
    for raw in preview.candidates:
        candidate = s.Candidate.model_validate(raw)
        current = eligible_candidate(session, rule, candidate.transaction_id)
        if current is None or current != candidate:
            raise HouseholdError("preview is stale; create and approve a new preview", status=409)
    for raw in preview.candidates:
        candidate = s.Candidate.model_validate(raw)
        body = s.ClassificationWrite(
            expected_revision=candidate.expected_revision,
            treatment="expense" if rule.treatment == "expense" else "income",
            merchant_id=merchant.id,
            allocations=[s.Split(category_id=rule.category_id, amount=candidate.source_amount)],
            explanation=f"rule {rule.id} version {rule.version}: {rule.explanation}",
        )
        save_classification(session, candidate.transaction_id, body, rule=rule, action="rule_apply")
    before = s.PreviewOut.model_validate(preview).model_dump(mode="json")
    preview.applied = True
    session.flush()
    audit(
        session,
        "preview",
        preview.id,
        "apply",
        before,
        s.PreviewOut.model_validate(preview).model_dump(mode="json"),
    )
    return preview


def undo_classification(session: Session, key: uuid.UUID, body: s.Undo) -> m.Classification:
    """Restore an audited prior state as a new protected manual revision."""
    lock_household(session)
    event = require(session, m.Audit, body.audit_id)
    if event.subject_type != "classification" or event.subject_id != key:
        raise HouseholdError("audit event does not belong to this classification")
    current = require(session, m.Classification, key)
    check_revision(current.revision, body.expected_revision)
    if event.before:
        old = s.ClassificationOut.model_validate(event.before)
        write = s.ClassificationWrite(
            expected_revision=current.revision,
            treatment=old.treatment,
            merchant_id=old.merchant_id,
            identity_confirmed=old.identity_confirmed,
            allocations=old.allocations,
            links=old.links,
            detail_links=old.detail_links,
            explanation=f"undo audit {event.id}",
        )
    else:
        write = s.ClassificationWrite(
            expected_revision=current.revision,
            treatment="unclassified",
            explanation=f"undo audit {event.id}",
        )
    merchant_id = current.merchant_id
    result = save_classification(session, key, write, action="undo")
    if merchant_id:
        disable_rule(session, merchant_id, "classification undone; explicit rule review required")
    return result


def upsert_payment_detail(session: Session, body: s.PaymentDetailWrite) -> m.PaymentDetail:
    """Idempotent detail-only provider store; caller owns transaction/write intent."""
    lock_household(session)
    detail = session.scalar(
        select(m.PaymentDetail)
        .where(
            m.PaymentDetail.provider == body.provider,
            m.PaymentDetail.source_account_id == body.source_account_id,
            m.PaymentDetail.external_id == body.external_id,
        )
        .with_for_update()
    )
    values = body.model_dump()
    values["source_fields"] = body.source_fields.model_dump(mode="json")
    if detail is None:
        detail = m.PaymentDetail(**values)
        session.add(detail)
    elif any(
        (
            not _same_instant(detail.ts, value)
            if field == "ts" and isinstance(value, datetime)
            else getattr(detail, field) != value
        )
        for field, value in values.items()
        if field != "connection_id"
    ):
        detail.revision += 1
        for field, value in values.items():
            setattr(detail, field, value)
    detail.connection_id = body.connection_id
    detail.last_seen_at = m.now()
    session.flush()
    return detail


def on_bank_sync(
    session: Session,
    *,
    inserted_ids: list[uuid.UUID],
    changed_ids: list[uuid.UUID],
) -> int:
    """Classify only newly inserted movements; historical rows require preview.

    Re-imports preserve all prior decisions. Changed source facts invalidate
    reporting/review state rather than silently redistributing manual splits.
    """
    lock_household(session)
    writes = 0
    for key in changed_ids:
        record = session.get(m.Classification, key)
        if record is None:
            continue
        out = classification_out(session, record)
        if not out.source_changed:
            continue
        before = out.model_dump(mode="json")
        record.review_state = "needs_review"
        record.revision += 1
        session.flush()
        audit(
            session,
            "classification",
            key,
            "source_changed",
            before,
            classification_out(session, record).model_dump(mode="json"),
        )
        if record.merchant_id:
            disable_rule(
                session, record.merchant_id, "source movement changed; confirm identity again"
            )
        writes += 1
    for key in inserted_ids:
        suggestion = suggest(session, key)
        if suggestion.rule is None or suggestion.rule.state != "active":
            continue
        rule = require(session, m.Rule, suggestion.rule.id)
        candidate = eligible_candidate(session, rule, key)
        category = require(session, m.Category, rule.category_id) if rule.category_id else None
        if candidate is None or category is None or category.archived:
            continue
        save_classification(
            session,
            key,
            s.ClassificationWrite(
                expected_revision=0,
                treatment="expense" if rule.treatment == "expense" else "income",
                merchant_id=rule.merchant_id,
                allocations=[s.Split(category_id=category.id, amount=candidate.source_amount)],
                explanation=f"new source movement: rule {rule.id} version {rule.version}",
            ),
            rule=rule,
            action="rule_apply",
        )
        writes += 1
    return writes


def invalidate_account_sources(session: Session, account_id: uuid.UUID) -> int:
    """Review any classified movement affected by an account-currency resync."""
    ids = session.scalars(
        select(m.Classification.transaction_id)
        .join(m.SourceTransaction, m.SourceTransaction.id == m.Classification.transaction_id)
        .where(m.SourceTransaction.account_id == account_id)
        .where(m.Classification.review_state != "needs_review")
        .execution_options(yield_per=100)
    )
    return sum(on_bank_sync(session, inserted_ids=[], changed_ids=[key]) for key in ids)
