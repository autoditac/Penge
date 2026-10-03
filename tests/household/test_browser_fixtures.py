"""In-memory invariants for the additional connected browser seed."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from penge.api.merchant_reference import store
from penge.api.merchant_reference.store_models import ReferenceBase
from penge.household import models as m
from penge.household import schemas as s
from penge.household import service
from tests.household.browser_fixtures import seed_browser_journeys


def test_device_seeds_are_independent_and_preserve_bank_grain(engine: Engine) -> None:
    ReferenceBase.metadata.create_all(engine)
    account_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(m.Account(id=account_id, provider="gls", currency="EUR"))
        session.commit()
    seed_browser_journeys(engine, account_id)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(m.SourceTransaction)) == 10
        external_ids = list(session.scalars(select(m.SourceTransaction.external_id)))
        assert len(set(external_ids)) == 10
        assert all(key is not None and key.startswith("synthetic-browser-") for key in external_ids)
        assert session.scalar(select(func.count()).select_from(m.PaymentDetail)) == 4
        assert session.scalar(select(func.count()).select_from(m.DetailLink)) == 0
        merchants: list[m.Merchant] = list(session.scalars(select(m.Merchant)))
        for merchant in merchants:
            rule = service.latest_rule(session, merchant)
            assert rule is not None and rule.state == "active"
            preview = service.preview_rule(session, rule.id, 100, 0)
            assert len(preview.candidates) == 1
            candidate = s.Candidate.model_validate(preview.candidates[0])
            transaction = session.get(m.SourceTransaction, candidate.transaction_id)
            assert transaction is not None and transaction.description is not None
            assert "history" in transaction.description
    assert store.search(engine, "Synthetic browser desktop public").match_status == "unique"
