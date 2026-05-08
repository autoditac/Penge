"""Tests for :mod:`penge.ingest.enablebanking.client` using ``httpx.MockTransport``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from penge.ingest.enablebanking.client import (
    Client,
    ClientConfig,
    EnableBankingError,
    default_consent_until,
)
from penge.ingest.enablebanking.models import TransactionsResponse


@pytest.fixture(scope="module")
def keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def _make_client(
    keypair: tuple[str, str], handler: httpx.MockTransport
) -> Client:
    private_pem, _ = keypair
    config = ClientConfig(
        application_id="test-app",
        private_key_pem=private_pem,
        base_url="https://api.test",
    )
    return Client(config, transport=handler)


def test_default_consent_until_is_in_the_future() -> None:
    now = datetime.now(UTC)
    assert default_consent_until(days=7) > now


def test_jwt_is_signed_with_kid_and_rs256(keypair: tuple[str, str]) -> None:
    _private_pem, public_pem = keypair
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"balances": []})

    with _make_client(keypair, httpx.MockTransport(handler)) as client:
        client.get_account_balances("acct-uid")

    token = captured["auth"].removeprefix("Bearer ")
    header = pyjwt.get_unverified_header(token)
    assert header["alg"] == "RS256"
    assert header["kid"] == "test-app"
    decoded = pyjwt.decode(
        token,
        public_pem,
        algorithms=["RS256"],
        audience="api.enablebanking.com",
        issuer="enablebanking.com",
    )
    assert decoded["iss"] == "enablebanking.com"
    assert decoded["aud"] == "api.enablebanking.com"


def test_token_is_cached_across_requests(keypair: tuple[str, str]) -> None:
    seen_tokens: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_tokens.append(request.headers["authorization"])
        return httpx.Response(200, json={"balances": []})

    with _make_client(keypair, httpx.MockTransport(handler)) as client:
        client.get_account_balances("a")
        client.get_account_balances("b")

    assert len(seen_tokens) == 2
    assert seen_tokens[0] == seen_tokens[1]


def test_error_response_raises(keypair: tuple[str, str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "consent_expired"})

    with _make_client(keypair, httpx.MockTransport(handler)) as client, pytest.raises(
        EnableBankingError
    ) as excinfo:
        client.get_account_balances("a")
    assert excinfo.value.status_code == 403


def test_start_authorization_posts_expected_body(keypair: tuple[str, str]) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "url": "https://psu.example/consent/abc",
                "authorization_id": "auth-123",
            },
        )

    valid_until = datetime(2026, 11, 1, tzinfo=UTC)
    with _make_client(keypair, httpx.MockTransport(handler)) as client:
        resp = client.start_authorization(
            aspsp_name="GLS Bank",
            aspsp_country="DE",
            redirect_url="https://localhost/cb",
            valid_until=valid_until,
            state="csrf-1",
        )

    assert resp.url == "https://psu.example/consent/abc"
    assert resp.authorization_id == "auth-123"
    assert captured["url"].endswith("/auth")
    body = captured["body"]
    assert body["aspsp"] == {"name": "GLS Bank", "country": "DE"}
    assert body["redirect_url"] == "https://localhost/cb"
    assert body["state"] == "csrf-1"
    assert body["psu_type"] == "personal"
    assert body["access"]["balances"] is True
    assert body["access"]["transactions"] is True


def _txn_payload(entry_ref: str) -> dict[str, Any]:
    return {
        "entry_reference": entry_ref,
        "transaction_amount": {"amount": "1.23", "currency": "EUR"},
        "credit_debit_indicator": "CRDT",
        "status": "BOOK",
        "booking_date": "2026-05-01",
    }


def test_get_account_transactions_paginates(keypair: tuple[str, str]) -> None:
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        if request.url.params.get("continuation_key") == "page2":
            return httpx.Response(
                200,
                json={
                    "transactions": [_txn_payload("E3")],
                    "continuation_key": None,
                },
            )
        return httpx.Response(
            200,
            json={
                "transactions": [_txn_payload("E1"), _txn_payload("E2")],
                "continuation_key": "page2",
            },
        )

    with _make_client(keypair, httpx.MockTransport(handler)) as client:
        resp: TransactionsResponse = client.get_account_transactions(
            "acct-uid",
            date_from="2026-01-01",
            date_to="2026-05-01",
        )

    assert [t.entry_reference for t in resp.transactions] == ["E1", "E2", "E3"]
    assert resp.continuation_key is None
    assert len(calls) == 2
    assert calls[0]["transaction_status"] == "BOOK"
    assert "continuation_key" not in calls[0]
    assert calls[1]["continuation_key"] == "page2"


def test_get_account_transactions_omits_none_params(keypair: tuple[str, str]) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request.url.params)
        return httpx.Response(200, json={"transactions": []})

    with _make_client(keypair, httpx.MockTransport(handler)) as client:
        client.get_account_transactions("acct-uid")

    assert "strategy" not in captured
    assert "date_from" not in captured
    assert "date_to" not in captured
    assert captured["transaction_status"] == "BOOK"


def test_amount_decimal_preserved(keypair: tuple[str, str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "balances": [
                    {
                        "name": "Closing",
                        "balance_amount": {"amount": "1234.56", "currency": "EUR"},
                        "balance_type": "CLBD",
                        "reference_date": "2026-05-01",
                    }
                ]
            },
        )

    with _make_client(keypair, httpx.MockTransport(handler)) as client:
        resp = client.get_account_balances("a")

    assert resp.balances[0].balance_amount.amount == Decimal("1234.56")
