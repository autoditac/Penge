"""API contracts for the public merchant-reference index."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from penge.api.merchant_reference import routes, store


@pytest.fixture
def engine() -> Iterator[Engine]:
    test_engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        yield test_engine
    finally:
        test_engine.dispose()


def _empty_state() -> store.ReferenceIndexState:
    return store.ReferenceIndexState(
        source_id="name-suggestion-index",
        status="never_refreshed",
        source_version=None,
        candidate_version=None,
        source_url=None,
        license=None,
        checksum_sha256=None,
        package_integrity=None,
        candidate_integrity=None,
        source_generated_at=None,
        last_checked_at=None,
        last_attempt_at=None,
        last_success_at=None,
        snapshot_started_at=None,
        snapshot_completed_at=None,
        record_count=None,
        active_generation_id=None,
        error_code=None,
        error_message=None,
    )


def test_reference_status_exposes_public_provenance_and_sanitized_errors(
    client: TestClient,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_id = uuid4()
    state = _empty_state()
    state = replace(
        state,
        status="stale",
        source_version="8.0.20260918",
        source_url="https://cdn.jsdelivr.net/npm/name-suggestion-index@8.0.20260918/dist/json/nsi.json",
        license="BSD-3-Clause",
        checksum_sha256="a" * 64,
        package_integrity="sha512-YWJj",
        source_generated_at=datetime(2026, 9, 18, tzinfo=UTC),
        last_success_at=datetime(2026, 9, 19, tzinfo=UTC),
        record_count=19_119,
        active_generation_id=generation_id,
        error_code="source_timeout",
        error_message="Public package request timed out.",
    )

    def fake_get_engine() -> Engine:
        return engine

    monkeypatch.setattr(routes, "get_import_engine", fake_get_engine)
    monkeypatch.setattr(store, "get_status", lambda _engine: state)

    response = client.get("/vendors/reference-index/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_id"] == "name-suggestion-index"
    assert payload["status"] == "stale"
    assert payload["source_version"] == "8.0.20260918"
    assert payload["license"] == "BSD-3-Clause"
    assert payload["attribution"] == (
        "Name Suggestion Index contributors; OpenStreetMap contributors"
    )
    assert payload["checksum_sha256"] == "a" * 64
    assert payload["record_count"] == 19_119
    assert payload["active_generation_id"] == str(generation_id)
    assert payload["error_code"] == "source_timeout"
    assert "account" not in payload


def test_reference_search_returns_local_ambiguous_matches_and_truncation(
    client: TestClient,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_match = store.ReferenceMatch(
        source_entity_id="synthetic-acme-dk",
        label="Acme",
        aliases=("Acme", "ACME Denmark"),
        category_path="brands/shop/supermarket",
        wikidata_id="Q123",
        source_version="8.0.20260918",
        source_url="https://example.invalid/public-catalog",
        license="BSD-3-Clause",
        match_kind="exact_alias",
    )
    observed: list[tuple[str, int]] = []

    def fake_search(
        _engine: Engine,
        query: str,
        *,
        limit: int,
    ) -> store.ReferenceSearch:
        observed.append((query, limit))
        return store.ReferenceSearch(
            match_status="ambiguous",
            source_status="stale",
            source_version="8.0.20260918",
            matches=(expected_match,),
            truncated=True,
        )

    def fake_get_engine() -> Engine:
        return engine

    monkeypatch.setattr(routes, "get_import_engine", fake_get_engine)
    monkeypatch.setattr(store, "search", fake_search)

    response = client.get("/vendors/reference-index/search?q=Acme&limit=7")

    assert response.status_code == 200
    assert observed == [("Acme", 7)]
    assert response.json() == {
        "match_status": "ambiguous",
        "source_status": "stale",
        "source_version": "8.0.20260918",
        "matches": [
            {
                "source_entity_id": "synthetic-acme-dk",
                "label": "Acme",
                "aliases": ["Acme", "ACME Denmark"],
                "category_path": "brands/shop/supermarket",
                "wikidata_id": "Q123",
                "source_version": "8.0.20260918",
                "source_url": "https://example.invalid/public-catalog",
                "license": "BSD-3-Clause",
                "match_kind": "exact_alias",
            }
        ],
        "limit": 7,
        "truncated": True,
    }


def test_reference_search_rejects_invalid_search_length(client: TestClient) -> None:
    assert client.get("/vendors/reference-index/search?q=").status_code == 422
    assert client.get(f"/vendors/reference-index/search?q={'x' * 101}").status_code == 422
