"""End-to-end tests for the connections API against a real Postgres.

The Enable Banking client is faked; the route → service → store →
loader → Postgres path is exercised for real, so these tests also
guard the loader write path the CLI sync shares.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import text

from penge.api.connections import service, store
from penge.ops.net_worth_refresh import exclusive_lock
from tests.api.connections.fakes import eb_error

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.engine import Engine

    from penge.ingest.enablebanking.client import Client
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
    providers = {p["provider"]: p for p in resp.json()["providers"]}
    assert set(providers) == {"gls", "ebank", "lunar", "paypal"}
    assert providers["paypal"] == {
        "provider": "paypal",
        "aspsp_name": "PayPal",
        "aspsp_country": "DE",
        "default_currency": "EUR",
        "psu_type": "personal",
        "data_role": "payment_detail",
    }


def test_paypal_link_requests_personal_psu_type(
    client: TestClient, fake_client: FakeClient
) -> None:
    linked = _link(client, provider="paypal")

    assert isinstance(linked["connection_id"], str)
    assert fake_client.requested_psu_types == ["personal"]
    assert fake_client.aspsp_name == "PayPal"
    assert fake_client.aspsp_country == "DE"


def test_paypal_sync_is_detail_only_and_reconsent_preserves_source_identity(
    client: TestClient,
    engine: Engine,
    fake_client: FakeClient,
) -> None:
    fake_client.stable_entry_reference = "synthetic-paypal-entry"
    fake_client.session_accounts = [
        fake_client.session_accounts[0].model_copy(
            update={"uid": "paypal-session-account-1", "identification_hash": "stable-paypal-hash"}
        )
    ]

    first_link = _link(client, provider="paypal")
    first_authorized = client.post(
        "/connections/authorize",
        json={"code": "first-code", "state": first_link["state"]},
    )
    assert first_authorized.status_code == 200, first_authorized.text
    first_sync = client.post(f"/connections/{first_link['connection_id']}/sync")
    assert first_sync.status_code == 200, first_sync.text
    assert first_sync.json()["transactions"] == 0
    assert first_sync.json()["holding_snapshots"] == 0
    assert first_sync.json()["payment_details"] == 1
    with engine.connect() as conn:
        first_detail_id: uuid.UUID = conn.execute(
            text(
                "select id from household_payment_detail "
                "where provider = 'paypal' and external_id = 'synthetic-paypal-entry'"
            )
        ).scalar_one()

    fake_client.session_accounts = [
        fake_client.session_accounts[0].model_copy(update={"uid": "paypal-session-account-2"})
    ]
    renewed_link = _link(client, provider="paypal")
    renewed_authorized = client.post(
        "/connections/authorize",
        json={"code": "renewed-code", "state": renewed_link["state"]},
    )
    assert renewed_authorized.status_code == 200, renewed_authorized.text
    renewed_sync = client.post(f"/connections/{renewed_link['connection_id']}/sync")
    assert renewed_sync.status_code == 200, renewed_sync.text
    assert renewed_sync.json()["payment_details"] == 1
    assert fake_client.balance_calls == []

    with engine.connect() as conn:
        details = conn.execute(
            text(
                "select id, connection_id, source_account_id, external_id, revision "
                "from household_payment_detail where provider = 'paypal'"
            )
        ).all()
        account_count: int = conn.execute(
            text("select count(*) from account where provider = 'paypal'")
        ).scalar_one()
        transaction_count: int = conn.execute(
            text(
                'select count(*) from "transaction" where account_id in '
                "(select id from account where provider = 'paypal')"
            )
        ).scalar_one()
        snapshot_count: int = conn.execute(
            text(
                "select count(*) from holding_snapshot where account_id in "
                "(select id from account where provider = 'paypal')"
            )
        ).scalar_one()

    assert len(details) == 1
    detail_id, connection_id, source_account_id, external_id, revision = details[0]
    assert detail_id == first_detail_id
    assert connection_id == uuid.UUID(str(renewed_link["connection_id"]))
    assert source_account_id == "DE:stable-paypal-hash"
    assert external_id == "synthetic-paypal-entry"
    assert revision == 1
    assert account_count == transaction_count == snapshot_count == 0


def test_list_empty(client: TestClient) -> None:
    resp = client.get("/connections")
    assert resp.status_code == 200
    assert resp.json() == {"connections": []}


def test_link_authorize_sync_happy_path(client: TestClient, engine: Engine, tmp_path: Path) -> None:
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
    assert (tmp_path / "refresh-state" / "pending").exists()

    with engine.connect() as conn:
        accounts: int = conn.execute(text("select count(*) from account")).scalar_one()
        txns: int = conn.execute(text('select count(*) from "transaction"')).scalar_one()
    assert accounts == 1
    assert txns == 1


def test_sync_persists_snapshot_when_aspsp_omits_reference_date(
    client: TestClient, engine: Engine, fake_client: FakeClient
) -> None:
    """GLS/EB/Lunar return balances with no reference_date.

    The loader must still write a holding snapshot, stamped with today's
    date, so these accounts contribute to net worth instead of showing €0.
    """
    fake_client.balance_without_reference_date = True

    linked = _link(client)
    state = linked["state"]
    connection_id = linked["connection_id"]

    authorized = client.post(
        "/connections/authorize",
        json={"code": "code-abc", "state": state},
    )
    assert authorized.status_code == 200, authorized.text

    before = datetime.now(UTC).date()
    synced = client.post(f"/connections/{connection_id}/sync")
    after = datetime.now(UTC).date()
    assert synced.status_code == 200, synced.text
    assert synced.json()["holding_snapshots"] >= 1

    with engine.connect() as conn:
        rows = conn.execute(text("select as_of, market_value from holding_snapshot")).all()
    assert len(rows) == 1
    as_of, market_value = rows[0]
    # Stamped with the sync date; allow the UTC day to roll over mid-test.
    assert as_of in {before, after}
    assert market_value == Decimal("100.00")


def test_repeated_sync_reports_no_data_writes(
    client: TestClient, engine: Engine, fake_client: FakeClient
) -> None:
    """An idempotent repeat must not trigger a downstream mart refresh."""
    linked = _link(client)
    client.post("/connections/authorize", json={"code": "c", "state": linked["state"]})
    first = service.sync(
        engine,
        cast("Client", fake_client),
        connection_id=uuid.UUID(str(linked["connection_id"])),
    )
    second = service.sync(
        engine,
        cast("Client", fake_client),
        connection_id=uuid.UUID(str(linked["connection_id"])),
    )

    assert first.writes > 0
    assert second.writes == 0
    assert second.transactions == 1
    assert second.holding_snapshots == 1


def test_account_corrections_survive_sync_for_two_accounts(
    client: TestClient, engine: Engine, fake_client: FakeClient, tmp_path: Path
) -> None:
    """Corrections on one consent do not affect another account or revert on sync."""
    linked = _link(client, provider="ebank")
    client.post("/connections/authorize", json={"code": "c", "state": linked["state"]})
    second = fake_client.session_accounts[0].model_copy(
        update={"uid": "uid-savings", "name": "Synthetic Savings"}
    )
    fake_client.session_accounts.append(second)
    assert client.post(f"/connections/{linked['connection_id']}/sync").status_code == 200

    with engine.begin() as conn:
        owner: uuid.UUID = conn.execute(
            text("insert into entity (name, kind) values ('Test Child', 'person') returning id")
        ).scalar_one()
        rows = conn.execute(
            text("select id, external_id from account where provider = 'ebank'")
        ).all()
    ids = {external_id: str(account_id) for account_id, external_id in rows}

    owner_response = client.patch(
        f"/accounts/{ids['uid-1']}/metadata", json={"entity_id": str(owner)}
    )
    kind_response = client.patch(
        f"/accounts/{ids['uid-savings']}/metadata", json={"kind": "savings"}
    )
    assert owner_response.status_code == 200, owner_response.text
    assert kind_response.status_code == 200, kind_response.text
    assert owner_response.json()["entity_id"] == str(owner)
    assert kind_response.json()["kind"] == "savings"
    assert (tmp_path / "refresh-state" / "pending").exists()
    assert client.post(f"/connections/{linked['connection_id']}/sync").status_code == 200

    with engine.connect() as conn:
        corrected = conn.execute(
            text(
                "select external_id, entity_id, kind, entity_override_id, kind_override "
                "from account where provider = 'ebank'"
            )
        ).all()
    by_uid = {
        external_id: (entity_id, kind, override_id, kind_override)
        for external_id, entity_id, kind, override_id, kind_override in corrected
    }
    assert by_uid["uid-1"] == (owner, "checking", owner, None)
    assert by_uid["uid-savings"][1:] == ("savings", None, "savings")
    assert by_uid["uid-savings"][0] != owner


def test_account_correction_rejects_invalid_inputs(client: TestClient, engine: Engine) -> None:
    linked = _link(client)
    client.post("/connections/authorize", json={"code": "c", "state": linked["state"]})
    client.post(f"/connections/{linked['connection_id']}/sync")
    with engine.connect() as conn:
        account_id: uuid.UUID = conn.execute(text("select id from account")).scalar_one()
    path = f"/accounts/{account_id}/metadata"

    assert client.patch(path, json={}).status_code == 422
    assert client.patch(path, json={"kind": "pension"}).status_code == 422
    assert client.patch(path, json={"entity_id": None}).status_code == 422
    assert client.patch(path, json={"entity_id": str(uuid.uuid4())}).status_code == 422
    missing = client.patch(f"/accounts/{uuid.uuid4()}/metadata", json={"kind": "savings"})
    assert missing.status_code == 404
    with engine.connect() as conn:
        assert conn.execute(text("select kind_override from account")).scalar_one() is None


def test_sync_returns_unavailable_while_refresh_lock_is_held(
    client: TestClient, tmp_path: Path
) -> None:
    linked = _link(client)
    client.post("/connections/authorize", json={"code": "c", "state": linked["state"]})

    with exclusive_lock(tmp_path / "refresh-state" / "refresh.lock"):
        response = client.post(f"/connections/{linked['connection_id']}/sync")

    assert response.status_code == 503
    assert "refresh lock is already held" in response.json()["detail"]


def test_sync_reports_committed_writes_before_later_account_failure(
    client: TestClient, engine: Engine, fake_client: FakeClient
) -> None:
    linked = _link(client)
    client.post("/connections/authorize", json={"code": "c", "state": linked["state"]})
    second = fake_client.session_accounts[0].model_copy(
        update={"uid": "uid-2", "name": "Synthetic Savings"}
    )
    fake_client.session_accounts.append(second)
    fake_client.fail_transactions_for_uid = "uid-2"
    observed_writes: list[int] = []

    with pytest.raises(service.ConnectionError) as raised:
        service.sync(
            engine,
            cast("Client", fake_client),
            connection_id=uuid.UUID(str(linked["connection_id"])),
            on_write=observed_writes.append,
        )

    assert raised.value.message == "Synthetic second account failure"
    assert sum(observed_writes) > 0
    with engine.connect() as connection:
        assert connection.execute(text('select count(*) from "transaction"')).scalar_one() == 1


def test_eligible_connections_exclude_expired_consent(client: TestClient, engine: Engine) -> None:
    linked = _link(client)
    client.post("/connections/authorize", json={"code": "c", "state": linked["state"]})

    assert [record.id for record in store.list_eligible_connections(engine)] == [
        uuid.UUID(str(linked["connection_id"]))
    ]

    with engine.begin() as connection:
        connection.execute(
            store.bank_connection_table.update()
            .where(store.bank_connection_table.c.id == uuid.UUID(str(linked["connection_id"])))
            .values(valid_until=datetime(2020, 1, 1, tzinfo=UTC))
        )

    assert store.list_eligible_connections(engine) == []


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


def test_sync_dedupes_duplicate_entry_references(
    client: TestClient, fake_client: FakeClient, engine: Engine
) -> None:
    # Some ASPSPs return the same entry_reference twice in one page. The
    # upsert must collapse them, not crash with ON CONFLICT DO UPDATE
    # CardinalityViolation. Regression guard for #240.
    linked = _link(client)
    client.post("/connections/authorize", json={"code": "c", "state": linked["state"]})
    fake_client.duplicate_entry_reference = True

    synced = client.post(f"/connections/{linked['connection_id']}/sync")

    assert synced.status_code == 200, synced.text
    assert synced.json()["connection"]["last_sync_status"] == "ok"
    with engine.connect() as conn:
        rows = conn.execute(text('select amount, description from "transaction"')).all()
    # Exactly one row survives, and it is the *last* of the two duplicates
    # (amount -56.78 / "synthetic-dup"), per last-write-wins dedup. DBIT
    # entries are stored with a negative sign.
    assert len(rows) == 1
    amount, description = rows[0]
    assert amount == Decimal("-56.78")
    assert description == "synthetic-dup"


def test_sync_falls_back_to_narrower_history_window(
    client: TestClient, fake_client: FakeClient, engine: Engine
) -> None:
    # PSD2: an ASPSP may reject the default 365-day window on unattended
    # repeat access with WRONG_TRANSACTIONS_PERIOD but still serve a
    # shorter window. Sync must retry with a narrower window and succeed
    # instead of failing the whole run. Regression guard for #242.
    linked = _link(client)
    client.post("/connections/authorize", json={"code": "c", "state": linked["state"]})
    fake_client.max_history_days = 90

    synced = client.post(f"/connections/{linked['connection_id']}/sync")

    assert synced.status_code == 200, synced.text
    body = synced.json()
    assert body["connection"]["last_sync_status"] == "ok"
    assert body["transactions"] >= 1
    # First attempt uses 365 days (rejected), retry uses 90 days (accepted).
    attempted = [w for w in fake_client.transaction_windows if w is not None]
    assert len(attempted) >= 2
    oldest_first = date.fromisoformat(attempted[0])
    oldest_retry = date.fromisoformat(attempted[1])
    assert oldest_retry > oldest_first


def test_sync_reports_error_when_no_window_is_accepted(
    client: TestClient, fake_client: FakeClient, engine: Engine
) -> None:
    # If even the narrowest fallback window is rejected, the sync surfaces
    # the WRONG_TRANSACTIONS_PERIOD error rather than silently reporting ok.
    linked = _link(client)
    client.post("/connections/authorize", json={"code": "c", "state": linked["state"]})
    fake_client.max_history_days = 0

    synced = client.post(f"/connections/{linked['connection_id']}/sync")

    assert synced.status_code >= 400, synced.text
    connection = client.get("/connections").json()["connections"][0]
    assert connection["status"] == "authorized"
    assert connection["last_sync_status"] == "error"
    assert connection["last_error"]["code"] == "WRONG_TRANSACTIONS_PERIOD"
    assert [record.id for record in store.list_eligible_connections(engine)] == [
        uuid.UUID(str(linked["connection_id"]))
    ]


def test_authorize_unknown_state_does_not_consume_code(
    client: TestClient, fake_client: FakeClient
) -> None:
    # A mismatched/stale state must fail *before* the single-use EB code is
    # spent, otherwise the code is burned and every retry gets
    # ALREADY_AUTHORIZED (orphaned consent). Regression guard for #238.
    _link(client)

    resp = client.post(
        "/connections/authorize",
        json={"code": "code-abc", "state": "00000000-0000-0000-0000-000000000000"},
    )

    assert resp.status_code == 404, resp.text
    assert fake_client.authorize_calls == 0
    connection = client.get("/connections").json()["connections"][0]
    assert connection["status"] == "linking"


def test_authorize_stale_error_state_does_not_consume_code(
    client: TestClient, engine: Engine, fake_client: FakeClient
) -> None:
    # record_error keeps the old `state` on a failed row. A freshly issued
    # code submitted with that stale state must NOT match the error row,
    # spend the code, and bind to the wrong connection. Regression for the
    # review follow-up on #238: preflight only accepts `linking` rows.
    linked = _link(client)
    consent_url = linked["consent_url"]
    assert isinstance(consent_url, str)
    stale_state = parse_qs(urlparse(consent_url).query)["state"][0]
    connection_id = uuid.UUID(str(linked["connection_id"]))

    store.record_error(engine, connection_id, error={"step": "authorize", "message": "boom"})

    resp = client.post(
        "/connections/authorize",
        json={"code": "code-fresh", "state": stale_state},
    )

    assert resp.status_code == 404, resp.text
    assert fake_client.authorize_calls == 0
    connection = client.get("/connections").json()["connections"][0]
    assert connection["status"] == "error"


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
