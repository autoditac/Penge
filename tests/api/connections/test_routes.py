"""End-to-end tests for the connections API against a real Postgres.

The Enable Banking client is faked; the route → service → store →
loader → Postgres path is exercised for real, so these tests also
guard the loader write path the CLI sync shares.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

from tests.api.connections.fakes import eb_error

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.engine import Engine

    from tests.api.connections.fakes import FakeClient


def _link(client: TestClient, provider: str = "gls") -> dict[str, object]:
    resp = client.post(
        "/connections/link",
        json={"provider": provider, "entity_name": "Rouven"},
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, object] = resp.json()
    return body


def test_list_aspsps(client: TestClient) -> None:
    resp = client.get("/connections/aspsps")
    assert resp.status_code == 200
    providers = {p["provider"] for p in resp.json()["providers"]}
    assert providers == {"gls", "ebank", "lunar"}


def test_list_empty(client: TestClient) -> None:
    resp = client.get("/connections")
    assert resp.status_code == 200
    assert resp.json() == {"connections": []}


def test_link_authorize_sync_happy_path(client: TestClient, engine: Engine) -> None:
    linked = _link(client)
    consent_url = linked["consent_url"]
    assert isinstance(consent_url, str)
    assert consent_url.startswith("https://auth.example/start")
    state = linked["state"]
    connection_id = linked["connection_id"]

    authorized = client.post(
        "/connections/authorize",
        json={"code": "code-abc", "state": state},
    )
    assert authorized.status_code == 200, authorized.text
    body = authorized.json()
    assert body["status"] == "authorized"
    assert body["accounts"][0]["iban_masked"].endswith("3000")
    # The raw IBAN must never be serialised.
    assert "532013000" not in authorized.text

    synced = client.post(f"/connections/{connection_id}/sync")
    assert synced.status_code == 200, synced.text
    sync_body = synced.json()
    assert sync_body["transactions"] >= 1
    assert sync_body["holding_snapshots"] >= 1
    assert sync_body["connection"]["last_sync_status"] == "ok"
    assert sync_body["connection"]["last_error"] is None

    with engine.connect() as conn:
        accounts = conn.execute(text("select count(*) from account")).scalar_one()
        txns = conn.execute(text('select count(*) from "transaction"')).scalar_one()
    assert accounts == 1
    assert txns == 1


def test_authorize_failure_records_debug_info(client: TestClient, fake_client: FakeClient) -> None:
    linked = _link(client)
    fake_client.authorize_error = eb_error(
        422, "ALREADY_AUTHORIZED", "Session is already authorized"
    )

    failed = client.post(
        "/connections/authorize",
        json={"code": "code-abc", "state": linked["state"]},
    )
    assert failed.status_code == 502
    assert "ALREADY_AUTHORIZED" in failed.json()["detail"]

    listed = client.get("/connections").json()["connections"]
    assert len(listed) == 1
    connection = listed[0]
    assert connection["status"] == "error"
    assert connection["last_error"]["step"] == "authorize"
    assert connection["last_error"]["code"] == "ALREADY_AUTHORIZED"
    assert connection["last_error"]["status_code"] == 422


def test_sync_expired_session_marks_reconsent(client: TestClient, fake_client: FakeClient) -> None:
    linked = _link(client)
    client.post("/connections/authorize", json={"code": "c", "state": linked["state"]})
    fake_client.session_status = "EXPIRED"

    resp = client.post(f"/connections/{linked['connection_id']}/sync")
    assert resp.status_code == 400
    assert "re-consent" in resp.json()["detail"]

    connection = client.get("/connections").json()["connections"][0]
    assert connection["status"] == "expired"
    assert connection["last_sync_status"] == "error"
    assert connection["last_error"]["step"] == "sync"


def test_unknown_provider_rejected(client: TestClient) -> None:
    resp = client.post(
        "/connections/link",
        json={"provider": "monzo", "entity_name": "Rouven"},
    )
    assert resp.status_code == 400
    assert "unknown provider" in resp.json()["detail"]


def test_sync_missing_connection_404(client: TestClient) -> None:
    resp = client.post("/connections/00000000-0000-0000-0000-000000000000/sync")
    assert resp.status_code == 404


def test_disabled_returns_503(disabled_client: TestClient) -> None:
    assert disabled_client.get("/connections/aspsps").status_code == 503
    assert disabled_client.get("/connections").status_code == 503
    link = disabled_client.post("/connections/link", json={"provider": "gls", "entity_name": "R"})
    assert link.status_code == 503
