"""Synthetic API journey (in-memory SQLite): hierarchy, exact split, audit."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from penge.household.models import Base
from tests.household.test_api import household_client  # noqa: F401
from tests.household.test_service import (
    test_payment_detail_timestamp_comparison_normalizes_naive_utc as check_timestamp_comparison,
)
from tests.household.test_service import (
    test_payment_detail_upsert_is_idempotent_across_fresh_sessions as check_fresh_session_upsert,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Share one synthetic in-memory SQLite connection across API requests."""
    database = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(database)
    try:
        yield database
    finally:
        database.dispose()


def test_payment_detail_timestamp_regressions_in_memory(
    engine: Engine,
    session: Session,
    synthetic_sources: dict[str, uuid.UUID],
) -> None:
    """Exercise the foundation regressions without its file-backed engine fixture."""
    check_timestamp_comparison()
    check_fresh_session_upsert(engine, session, synthetic_sources)


def test_nested_category_split_and_audit_journey(
    household_client: TestClient,  # noqa: F811
    session: Session,
    synthetic_sources: dict[str, uuid.UUID],
) -> None:
    session.commit()
    root = household_client.post(
        "/household/categories",
        json={"expected_revision": 0, "name": "Synthetic Food", "kind": "expense"},
    ).json()
    child = household_client.post(
        "/household/categories",
        json={
            "expected_revision": 0,
            "name": "Synthetic Produce",
            "kind": "expense",
            "parent_id": root["id"],
        },
    ).json()
    assert child["parent_id"] == root["id"]

    path = f"/household/transactions/{synthetic_sources['gls']}/classification"
    saved = household_client.patch(
        path,
        json={
            "expected_revision": 0,
            "treatment": "expense",
            "allocations": [
                {"category_id": root["id"], "amount": "-2.00"},
                {"category_id": child["id"], "amount": "-10.34"},
            ],
            "explanation": "Synthetic exact split",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["source_amount"] == "-12.3400"

    bad = household_client.patch(
        path,
        json={
            "expected_revision": saved.json()["revision"],
            "treatment": "expense",
            "allocations": [{"category_id": root["id"], "amount": "-12.33"}],
            "explanation": "Synthetic non-conserving split",
        },
    )
    assert bad.status_code in {409, 422}, bad.text

    audit_response = household_client.get(
        "/household/audit", params={"subject_id": str(synthetic_sources["gls"])}
    )
    assert audit_response.status_code == 200, audit_response.text
    gls_audit = [
        event
        for event in audit_response.json()
        if event["subject_type"] == "classification"
        and event["subject_id"] == str(synthetic_sources["gls"])
        and event["action"] == "save"
        and event["after"]["revision"] == saved.json()["revision"]
    ]
    assert len(gls_audit) == 1
    assert gls_audit[0]["before"] is None
    undone = household_client.post(
        f"/household/transactions/{synthetic_sources['gls']}/undo",
        json={
            "expected_revision": saved.json()["revision"],
            "audit_id": gls_audit[0]["id"],
        },
    )
    assert undone.status_code == 200, undone.text
    restored = undone.json()
    assert restored["revision"] == saved.json()["revision"] + 1
    assert restored["treatment"] == "unclassified"
    assert restored["review_state"] == "unclassified"
    assert restored["provenance"] == "manual"
    assert restored["allocations"] == []
    assert restored["source_amount"] == saved.json()["source_amount"]


def test_rule_preview_requires_approval_and_preserves_manual_override(
    household_client: TestClient,  # noqa: F811
    session: Session,
    synthetic_sources: dict[str, uuid.UUID],
) -> None:
    session.commit()
    category_response = household_client.post(
        "/household/categories",
        json={"expected_revision": 0, "name": "Synthetic groceries", "kind": "expense"},
    )
    assert category_response.status_code == 201, category_response.text
    category_id = category_response.json()["id"]
    merchant_response = household_client.post(
        "/household/merchants",
        json={
            "expected_revision": 0,
            "name": "Synthetic Market",
            "identity_kind": "stable",
            "confirmed": True,
        },
    )
    assert merchant_response.status_code == 201, merchant_response.text
    merchant_id = merchant_response.json()["id"]
    for provider in synthetic_sources:
        alias = household_client.post(
            "/household/aliases",
            json={
                "expected_revision": 0,
                "merchant_id": merchant_id,
                "provider": provider,
                "label": "Synthetic Market",
                "confirmed": True,
            },
        )
        assert alias.status_code == 201, alias.text

    learned = household_client.patch(
        f"/household/transactions/{synthetic_sources['gls']}/classification",
        json={
            "expected_revision": 0,
            "treatment": "expense",
            "merchant_id": merchant_id,
            "identity_confirmed": True,
            "allocations": [{"category_id": category_id, "amount": "-12.34"}],
            "explanation": "Synthetic confirmed merchant correction",
        },
    )
    assert learned.status_code == 200, learned.text
    rules = household_client.get("/household/rules", params={"merchant_id": merchant_id})
    assert rules.status_code == 200, rules.text
    [rule] = [row for row in rules.json() if row["state"] == "active"]
    preview = household_client.post(f"/household/rules/{rule['id']}/preview")
    assert preview.status_code == 201, preview.text
    assert {row["transaction_id"] for row in preview.json()["candidates"]} == {
        str(synthetic_sources["ebank"]),
        str(synthetic_sources["lunar"]),
    }
    for provider in ("ebank", "lunar"):
        unchanged = household_client.get(f"/household/transactions/{synthetic_sources[provider]}")
        assert unchanged.status_code == 200, unchanged.text
        assert unchanged.json()["classification"] is None

    manual = household_client.patch(
        f"/household/transactions/{synthetic_sources['ebank']}/classification",
        json={
            "expected_revision": 0,
            "treatment": "excluded",
            "explanation": "Synthetic protected human decision",
        },
    )
    assert manual.status_code == 200, manual.text
    stale = household_client.post(
        f"/household/previews/{preview.json()['id']}/apply", json={"approve": True}
    )
    assert stale.status_code == 409, stale.text
    unchanged = household_client.get(f"/household/transactions/{synthetic_sources['lunar']}")
    assert unchanged.json()["classification"] is None

    fresh = household_client.post(f"/household/rules/{rule['id']}/preview")
    assert fresh.status_code == 201, fresh.text
    assert [row["transaction_id"] for row in fresh.json()["candidates"]] == [
        str(synthetic_sources["lunar"])
    ]
    applied = household_client.post(
        f"/household/previews/{fresh.json()['id']}/apply", json={"approve": True}
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] is True
    protected = household_client.get(f"/household/transactions/{synthetic_sources['ebank']}")
    assert protected.json()["classification"] == manual.json()
    classified = household_client.get(f"/household/transactions/{synthetic_sources['lunar']}")
    assert classified.json()["classification"]["provenance"] == "rule"
    assert classified.json()["classification"]["allocations"] == [
        {"category_id": category_id, "amount": "-12.3400"}
    ]
