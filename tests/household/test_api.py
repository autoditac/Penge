"""Household API tests using SQLite-backed dependency overrides."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from penge.api import household as household_api
from penge.household import models as m
from penge.household import service

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


@pytest.fixture
def household_client(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Exercise the real API routes with per-request SQLite sessions."""
    monkeypatch.setenv("PENGE_HOUSEHOLD_ENABLED", "true")
    app = FastAPI()
    app.include_router(household_api.router)

    def read_session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    def write_session_override() -> Iterator[Session]:
        try:
            with Session(engine) as session, session.begin():
                yield session
        except service.HouseholdError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    app.dependency_overrides[household_api.read_session] = read_session_override
    app.dependency_overrides[household_api.write_session] = write_session_override
    with TestClient(app) as client:
        yield client


def test_household_routes_return_503_when_feature_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The actual opt-in dependency denies requests before opening a database."""
    monkeypatch.delenv("PENGE_HOUSEHOLD_ENABLED", raising=False)
    app = FastAPI()
    app.include_router(household_api.router)
    with TestClient(app) as client:
        response = client.get("/household/categories")
    assert response.status_code == 503
    assert response.json()["detail"] == "household categorization is disabled"


def test_browse_paginates_filters_and_serializes_decimal_without_raw_data(
    household_client: TestClient,
    session: Session,
    synthetic_sources: dict[str, uuid.UUID],
) -> None:
    """Browse results are bounded, filterable, exact-decimal and schema-limited."""
    session.commit()
    category_response = household_client.post(
        "/household/categories",
        json={
            "expected_revision": 0,
            "name": "Synthetic groceries",
            "kind": "expense",
        },
    )
    assert category_response.status_code == 201
    category_id = category_response.json()["id"]
    response = household_client.patch(
        f"/household/transactions/{synthetic_sources['gls']}/classification",
        json={
            "expected_revision": 0,
            "treatment": "expense",
            "allocations": [{"category_id": category_id, "amount": "-12.34"}],
            "explanation": "Synthetic API classification",
        },
    )
    assert response.status_code == 200
    assert response.json()["source_amount"] == "-12.3400"
    assert response.json()["allocations"] == [{"category_id": category_id, "amount": "-12.3400"}]

    page = household_client.get("/household/transactions", params={"limit": 1})
    second_page = household_client.get("/household/transactions", params={"limit": 1, "offset": 1})
    assert page.status_code == second_page.status_code == 200
    assert len(page.json()) == len(second_page.json()) == 1
    assert page.json()[0]["transaction_id"] != second_page.json()[0]["transaction_id"]

    filtered = household_client.get(
        "/household/transactions",
        params={
            "provider": "gls",
            "currency": "EUR",
            "category_id": category_id,
            "treatment": "expense",
            "search": "Synthetic Market",
        },
    )
    assert filtered.status_code == 200
    [transaction] = filtered.json()
    assert transaction["provider"] == "gls"
    assert transaction["amount"] == "-12.3400"
    assert transaction["currency"] == "EUR"
    assert transaction["reporting_role"] == "bank_movement"
    assert transaction["classification"]["source_amount"] == "-12.3400"
    assert "raw" not in filtered.text.lower()
    assert "source_fields" not in filtered.text
    assert "iban" not in filtered.text.lower()

    session.expire_all()
    assert session.get(m.Classification, synthetic_sources["gls"]) is not None
    source_transaction = session.get(m.SourceTransaction, synthetic_sources["gls"])
    assert source_transaction is not None
    assert Decimal(source_transaction.amount) == Decimal("-12.34")


def test_bad_body_is_422_and_stale_classification_revision_is_409(
    household_client: TestClient,
    session: Session,
    synthetic_sources: dict[str, uuid.UUID],
) -> None:
    session.commit()
    invalid = household_client.patch(
        f"/household/transactions/{synthetic_sources['gls']}/classification",
        json={
            "expected_revision": 0,
            "treatment": "not-a-treatment",
            "explanation": "Synthetic invalid request",
        },
    )
    assert invalid.status_code == 422

    category = household_client.post(
        "/household/categories",
        json={"expected_revision": 0, "name": "Synthetic costs", "kind": "expense"},
    )
    category_id = category.json()["id"]
    path = f"/household/transactions/{synthetic_sources['gls']}/classification"
    valid_body = {
        "expected_revision": 0,
        "treatment": "expense",
        "allocations": [{"category_id": category_id, "amount": "-12.34"}],
        "explanation": "Synthetic valid request",
    }
    assert household_client.patch(path, json=valid_body).status_code == 200
    stale = household_client.patch(path, json=valid_body)
    assert stale.status_code == 409
    assert "revision conflict" in stale.json()["detail"]


def test_category_and_transaction_queries_enforce_pagination_limits(
    household_client: TestClient,
    session: Session,
    synthetic_sources: dict[str, uuid.UUID],
) -> None:
    session.commit()
    category = household_client.post(
        "/household/categories",
        json={"expected_revision": 0, "name": "Synthetic category", "kind": "expense"},
    )
    assert category.status_code == 201
    assert (
        household_client.get("/household/categories", params={"limit": 1}).json()[0]["name"]
        == "Synthetic category"
    )
    assert (
        household_client.get(
            "/household/transactions",
            params={"limit": 501},
        ).status_code
        == 422
    )
    assert (
        household_client.get(f"/household/transactions/{synthetic_sources['gls']}").json()["amount"]
        == "-12.3400"
    )


def test_unknown_category_and_malformed_uuid_are_reported(
    household_client: TestClient,
    session: Session,
    synthetic_sources: dict[str, uuid.UUID],
) -> None:
    session.commit()
    missing_category = uuid.uuid5(uuid.NAMESPACE_URL, "synthetic-missing-category")
    response = household_client.patch(
        f"/household/transactions/{synthetic_sources['gls']}/classification",
        json={
            "expected_revision": 0,
            "treatment": "expense",
            "allocations": [{"category_id": str(missing_category), "amount": "-12.34"}],
            "explanation": "Synthetic missing category",
        },
    )
    assert response.status_code == 404
    malformed = household_client.get("/household/transactions/not-a-uuid")
    assert malformed.status_code == 422
