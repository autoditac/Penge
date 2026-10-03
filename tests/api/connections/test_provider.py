"""Unit tests for the provider registry (no DB)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from penge.api.connections import service, store
from penge.api.connections.config import ConnectionsConfig
from penge.api.connections.provider import all_providers, get_provider
from penge.api.connections.routes import list_aspsps
from penge.ingest.enablebanking.loader import LoadResult
from penge.ingest.enablebanking.models import AccountResource, GetSessionResponse
from penge.ingest.paypal import loader as paypal_loader
from tests.api.connections.fakes import FakeClient

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from penge.ingest.enablebanking.client import Client


def test_known_providers() -> None:
    slugs = {p.slug for p in all_providers()}
    assert slugs == {"gls", "ebank", "lunar", "paypal"}


def test_gls_aspsp_name_matches_production_catalogue() -> None:
    gls = get_provider("gls")
    assert gls is not None
    assert gls.aspsp_name == "GLS Gemeinschaftsbank"
    assert gls.aspsp_country == "DE"


def test_lunar_is_danish_dkk() -> None:
    lunar = get_provider("lunar")
    assert lunar is not None
    assert lunar.aspsp_country == "DK"
    assert lunar.default_currency == "DKK"


def test_paypal_is_personal_detail_only_source() -> None:
    paypal = get_provider("paypal")
    assert paypal is not None
    assert paypal.aspsp_name == "PayPal"
    assert paypal.aspsp_country == "DE"
    assert paypal.psu_type == "personal"
    assert paypal.data_role == "payment_detail"
    assert not paypal.request_balances
    assert paypal.request_transactions
    assert paypal.sync_account is not None


def test_paypal_sync_uses_detail_loader_without_ledger_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paypal = get_provider("paypal")
    assert paypal is not None
    assert paypal.sync_account is not None
    expected = LoadResult(transactions=0, holding_snapshots=0, writes=1, payment_details=1)
    calls: list[dict[str, object]] = []

    def load_account(engine: Engine, **kwargs: object) -> LoadResult:
        _ = engine
        calls.append(kwargs)
        return expected

    monkeypatch.setattr(paypal_loader, "load_account", load_account)
    account = AccountResource(uid="session-account", identification_hash="stable-account")
    connection_id = uuid.UUID("00000000-0000-0000-0000-000000000331")
    fake_client = FakeClient()
    result = paypal.sync_account(
        cast("Engine", object()),
        client=cast("Client", fake_client),
        account=account,
        connection_id=connection_id,
        entity_name="Synthetic owner",
        date_from=date(2026, 1, 1),
        date_to=date(2026, 10, 3),
    )

    assert result == expected
    assert len(calls) == 1
    assert calls[0]["client"] is fake_client
    assert calls[0]["account"] == account
    assert calls[0]["connection_id"] == connection_id
    assert calls[0]["date_from"] == date(2026, 1, 1)
    assert calls[0]["date_to"] == date(2026, 10, 3)


def test_paypal_manual_sync_requires_unexpired_consent(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    record = store.ConnectionRecord(
        id=uuid.UUID("00000000-0000-0000-0000-000000000331"),
        provider="paypal",
        aspsp_name="PayPal",
        aspsp_country="DE",
        entity_name="Synthetic owner",
        status=store.STATUS_AUTHORIZED,
        state=None,
        authorization_id=None,
        session_id="synthetic-session",
        valid_until=now - timedelta(seconds=1),
        accounts=[],
        last_sync_at=None,
        last_sync_status=None,
        last_error=None,
        created_at=now,
        updated_at=now,
    )
    recorded: list[dict[str, object]] = []
    monkeypatch.setattr(store, "get_connection", lambda *_: record)
    monkeypatch.setattr(
        store,
        "record_error",
        lambda *_, **kwargs: recorded.append(kwargs),
    )
    fake_client = FakeClient()
    get_session_calls = 0
    original_get_session = fake_client.get_session

    def get_session(session_id: str) -> GetSessionResponse:
        nonlocal get_session_calls
        get_session_calls += 1
        return original_get_session(session_id)

    monkeypatch.setattr(fake_client, "get_session", get_session)

    with pytest.raises(service.ConnectionError) as raised:
        service.sync(
            cast("Engine", object()),
            cast("Client", fake_client),
            connection_id=record.id,
        )

    assert raised.value.message == "consent has expired; re-consent required"
    assert get_session_calls == 0
    assert recorded[0]["status"] == store.STATUS_EXPIRED
    assert recorded[0]["is_sync"] is True


def test_paypal_sync_records_sanitized_identity_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    record = store.ConnectionRecord(
        id=uuid.UUID("00000000-0000-0000-0000-000000000331"),
        provider="paypal",
        aspsp_name="PayPal",
        aspsp_country="DE",
        entity_name="Synthetic owner",
        status=store.STATUS_AUTHORIZED,
        state=None,
        authorization_id=None,
        session_id="synthetic-session",
        valid_until=now + timedelta(days=1),
        accounts=[],
        last_sync_at=None,
        last_sync_status=None,
        last_error=None,
        created_at=now,
        updated_at=now,
    )
    recorded: list[dict[str, object]] = []
    monkeypatch.setattr(store, "get_connection", lambda *_: record)
    monkeypatch.setattr(
        store,
        "record_error",
        lambda *_, **kwargs: recorded.append(kwargs),
    )

    with pytest.raises(service.ConnectionError) as raised:
        service.sync(
            cast("Engine", object()),
            cast("Client", FakeClient()),
            connection_id=record.id,
        )

    assert raised.value.code == "INVALID_PAYMENT_DETAIL"
    assert raised.value.message == "PayPal account has no stable primary identification_hash"
    assert recorded[0]["status"] == store.STATUS_AUTHORIZED
    assert recorded[0]["is_sync"] is True


def test_paypal_appears_with_personal_detail_only_route_metadata(tmp_path: Path) -> None:
    response = list_aspsps(
        ConnectionsConfig(
            enabled=True,
            redirect_url="https://penge.example/eb/callback",
            refresh_state_dir=tmp_path,
        )
    )

    paypal = next(provider for provider in response.providers if provider.provider == "paypal")
    assert paypal.psu_type == "personal"
    assert paypal.data_role == "payment_detail"


def test_paypal_link_requests_personal_psu_type(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)

    def create_linking(
        engine: Engine,
        *,
        provider: str,
        aspsp_name: str,
        aspsp_country: str,
        entity_name: str,
        state: str,
        authorization_id: str,
        valid_until: datetime,
    ) -> store.ConnectionRecord:
        _ = engine, authorization_id
        return store.ConnectionRecord(
            id=uuid.UUID("00000000-0000-0000-0000-000000000331"),
            provider=provider,
            aspsp_name=aspsp_name,
            aspsp_country=aspsp_country,
            entity_name=entity_name,
            status=store.STATUS_LINKING,
            state=state,
            authorization_id="synthetic-authorization",
            session_id=None,
            valid_until=valid_until,
            accounts=[],
            last_sync_at=None,
            last_sync_status=None,
            last_error=None,
            created_at=now,
            updated_at=now,
        )

    monkeypatch.setattr(store, "create_linking", create_linking)
    fake_client = FakeClient()
    service.start_link(
        cast("Engine", object()),
        cast("Client", fake_client),
        redirect_url="https://penge.example/eb/callback",
        provider_slug="paypal",
        entity_name="Synthetic owner",
    )

    assert fake_client.requested_psu_types == ["personal"]
    assert fake_client.requested_balances == [False]
    assert fake_client.requested_transactions == [True]
    assert fake_client.aspsp_name == "PayPal"


def test_unknown_provider_returns_none() -> None:
    assert get_provider("nope") is None
