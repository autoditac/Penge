"""Unit tests for the GoCardless client.

All HTTP traffic is stubbed via :class:`httpx.MockTransport` so these
tests run offline and never call the live API.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from penge.ingest.gocardless import (
    AccountBalances,
    AccountDetails,
    Client,
    ClientError,
    Institution,
    Requisition,
    Token,
    TokenCache,
    TransactionsPage,
)
from penge.ingest.gocardless.client import DEFAULT_BASE_URL


def _json(status: int, body: object) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(body), headers={"Content-Type": "application/json"})


def _build(handler):  # type: ignore[no-untyped-def]
    transport = httpx.MockTransport(handler)
    return Client("sid", "skey", cache=TokenCache(), transport=transport)


def test_token_issued_on_first_request_then_cached() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v2")
        calls.append(f"{request.method} {path}")
        if path == "/token/new/":
            return _json(
                200,
                {
                    "access": "ACCESS-1",
                    "access_expires": 86400,
                    "refresh": "REFRESH-1",
                    "refresh_expires": 2592000,
                },
            )
        if path == "/institutions/":
            assert request.headers["authorization"] == "Bearer ACCESS-1"
            return _json(200, [{"id": "BANK_DK", "name": "Bank", "countries": ["DK"]}])
        raise AssertionError(f"unexpected path {path}")

    client = _build(handler)
    institutions = client.list_institutions("DK")
    institutions2 = client.list_institutions("DK")  # cached token, no second /token/new/
    client.close()

    assert institutions == institutions2 == [Institution(id="BANK_DK", name="Bank", countries=("DK",))]
    assert calls.count("POST /token/new/") == 1
    assert calls.count("GET /institutions/") == 2


def test_401_triggers_token_refresh() -> None:
    state = {"issued": 0, "got_inst": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v2")
        if path == "/token/new/":
            state["issued"] += 1
            return _json(
                200,
                {
                    "access": f"ACCESS-{state['issued']}",
                    "access_expires": 86400,
                    "refresh": f"REFRESH-{state['issued']}",
                    "refresh_expires": 2592000,
                },
            )
        if path == "/institutions/":
            state["got_inst"] += 1
            # First call: pretend the token is suddenly invalid.
            if state["got_inst"] == 1:
                return _json(401, {"detail": "expired"})
            return _json(200, [])
        raise AssertionError(path)

    client = _build(handler)
    client.list_institutions("DK")
    client.close()

    assert state["issued"] == 2  # initial + after 401
    assert state["got_inst"] == 2


def test_4xx_raises_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token/new/"):
            return _json(403, {"detail": "bad credentials"})
        raise AssertionError

    client = _build(handler)
    with pytest.raises(ClientError) as exc:
        client.list_institutions("DK")
    client.close()
    assert exc.value.status == 403
    assert "bad credentials" in exc.value.body


def _seeded_client(handler):  # type: ignore[no-untyped-def]
    """Skip the token round-trip — simulate a warm cache."""
    cache = TokenCache()
    cache.store(
        Token(access="ACCESS", access_expires=86400, refresh="REFRESH", refresh_expires=2592000)
    )
    transport = httpx.MockTransport(handler)
    return Client("sid", "skey", cache=cache, transport=transport)


def test_create_and_get_requisition() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v2")
        if request.method == "POST" and path == "/requisitions/":
            captured["body"] = json.loads(request.content)
            return _json(
                201,
                {
                    "id": "REQ123",
                    "status": "CR",
                    "institution_id": "BANK_DK",
                    "reference": "ref-1",
                    "link": "https://ob.gocardless/req/REQ123",
                    "accounts": [],
                },
            )
        if path == "/requisitions/REQ123/":
            return _json(
                200,
                {
                    "id": "REQ123",
                    "status": "LN",
                    "institution_id": "BANK_DK",
                    "reference": "ref-1",
                    "accounts": ["acct-1", "acct-2"],
                },
            )
        raise AssertionError(path)

    client = _seeded_client(handler)
    created = client.create_requisition(
        institution_id="BANK_DK",
        redirect="https://example.invalid/return",
        reference="ref-1",
    )
    fetched = client.get_requisition("REQ123")
    accounts = list(client.iter_requisition_accounts("REQ123"))
    client.close()

    assert isinstance(created, Requisition)
    assert created.id == "REQ123"
    assert created.status == "CR"
    assert captured["body"] == {
        "institution_id": "BANK_DK",
        "redirect": "https://example.invalid/return",
        "reference": "ref-1",
    }
    assert fetched.status == "LN"
    assert fetched.accounts == ("acct-1", "acct-2")
    assert accounts == ["acct-1", "acct-2"]


def test_get_account_balances_parses_decimal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/accounts/acct-1/balances/")
        return _json(
            200,
            {
                "balances": [
                    {
                        "balanceAmount": {"amount": "1234.56", "currency": "DKK"},
                        "balanceType": "interimAvailable",
                        "referenceDate": "2026-05-06",
                    }
                ]
            },
        )

    client = _seeded_client(handler)
    bal = client.get_account_balances("acct-1")
    client.close()

    assert isinstance(bal, AccountBalances)
    assert len(bal.balances) == 1
    assert bal.balances[0].balance_amount.amount == Decimal("1234.56")
    assert bal.balances[0].balance_amount.currency == "DKK"
    assert bal.balances[0].balance_type == "interimAvailable"


def test_get_account_transactions_filters_and_unwraps() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/accounts/acct-1/transactions/")
        assert dict(request.url.params) == {"date_from": "2026-05-01", "date_to": "2026-05-06"}
        return _json(
            200,
            {
                "transactions": {
                    "booked": [
                        {
                            "transactionId": "T1",
                            "bookingDate": "2026-05-05",
                            "transactionAmount": {"amount": "-42.50", "currency": "DKK"},
                            "creditorName": "Netto",
                            "remittanceInformationUnstructured": "Groceries",
                        }
                    ],
                    "pending": [],
                }
            },
        )

    client = _seeded_client(handler)
    page = client.get_account_transactions(
        "acct-1",
        date_from="2026-05-01",
        date_to="2026-05-06",
    )
    client.close()

    assert isinstance(page, TransactionsPage)
    assert len(page.booked) == 1
    txn = page.booked[0]
    assert txn.transaction_id == "T1"
    assert txn.transaction_amount.amount == Decimal("-42.50")
    assert txn.creditor_name == "Netto"


def test_get_account_details_unwraps_account_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/accounts/acct-1/details/")
        return _json(
            200,
            {
                "account": {
                    "resourceId": "10010001",
                    "iban": "DK5000400440116243",
                    "currency": "DKK",
                    "ownerName": "Test Owner",
                    "name": "Lønkonto",
                    "product": "Current",
                }
            },
        )

    client = _seeded_client(handler)
    details = client.get_account_details("acct-1")
    client.close()

    assert isinstance(details, AccountDetails)
    assert details.account.iban == "DK5000400440116243"
    assert details.account.owner_name == "Test Owner"


def test_token_cache_persists_to_disk(tmp_path: Path) -> None:
    cache_file = tmp_path / "tokens.json"
    cache1 = TokenCache(path=cache_file)
    cache1.store(
        Token(access="A", access_expires=3600, refresh="R", refresh_expires=2592000),
        now=1_000_000.0,
    )
    assert cache_file.exists()
    # 0o600 — refresh token is sensitive.
    assert (cache_file.stat().st_mode & 0o777) == 0o600

    # New cache instance reads it back.
    cache2 = TokenCache(path=cache_file)
    assert cache2.access_token(now=1_000_100.0) == "A"
    assert cache2.refresh_token(now=1_000_100.0) == "R"


def test_token_cache_skews_access_expiry() -> None:
    cache = TokenCache()
    cache.store(
        Token(access="A", access_expires=3600, refresh="R", refresh_expires=2592000),
        now=0.0,
    )
    # 30s before expiry the access token should already be considered stale
    # (skew = 60s) so callers refresh proactively.
    assert cache.access_token(now=3600 - 30) is None
    assert cache.access_token(now=3600 - 120) == "A"


def test_default_base_url_is_official_endpoint() -> None:
    # Contract: documented production URL.
    assert DEFAULT_BASE_URL == "https://bankaccountdata.gocardless.com/api/v2"
