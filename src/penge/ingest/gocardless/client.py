"""Synchronous GoCardless Bank Account Data API client.

Endpoints implemented:

- ``POST /api/v2/token/new/`` — initial token issuance.
- ``POST /api/v2/token/refresh/`` — access-token refresh.
- ``GET  /api/v2/institutions/?country=XX``
- ``POST /api/v2/requisitions/``
- ``GET  /api/v2/requisitions/{id}/``
- ``GET  /api/v2/accounts/{id}/balances/``
- ``GET  /api/v2/accounts/{id}/transactions/``
- ``GET  /api/v2/accounts/{id}/details/``

The :class:`Client` is sync (``httpx.Client``) and re-entrant per
process. Token caching is delegated to :class:`TokenCache`, which can
be in-memory (default) or disk-backed (pass ``cache_path``).

This client is **transport only**. It returns Pydantic models; mapping
to the Penge ``transaction`` table happens elsewhere (see #14, #15).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from penge.ingest.gocardless.models import (
    AccountBalances,
    AccountDetails,
    Institution,
    Requisition,
    Token,
    TransactionsPage,
)

DEFAULT_BASE_URL = "https://bankaccountdata.gocardless.com/api/v2"

# Refresh the access token a minute before it actually expires so we
# never race the clock mid-request.
_ACCESS_REFRESH_SKEW_S = 60


class ClientError(RuntimeError):
    """Raised for any non-2xx response from the API."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"GoCardless API error {status}: {body}")
        self.status = status
        self.body = body


@dataclass
class TokenCache:
    """In-memory token store with optional disk persistence.

    The cache survives restarts when ``path`` is given. Refresh tokens
    last 30 days, so persisting them avoids forcing the operator
    through the consent flow daily.
    """

    path: Path | None = None
    _access: str | None = field(default=None, init=False)
    _refresh: str | None = field(default=None, init=False)
    _access_expires_at: float = field(default=0.0, init=False)
    _refresh_expires_at: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        if self.path is not None and self.path.exists():
            self._load()

    def store(self, token: Token, *, now: float | None = None) -> None:
        """Store a fresh ``Token`` and (optionally) persist to disk."""
        ts = time.time() if now is None else now
        self._access = token.access
        self._refresh = token.refresh
        self._access_expires_at = ts + token.access_expires
        self._refresh_expires_at = ts + token.refresh_expires
        if self.path is not None:
            self._save()

    def store_access(self, access: str, expires_in: int, *, now: float | None = None) -> None:
        """Update only the access half (used after ``/token/refresh/``)."""
        ts = time.time() if now is None else now
        self._access = access
        self._access_expires_at = ts + expires_in
        if self.path is not None:
            self._save()

    def access_token(self, *, now: float | None = None) -> str | None:
        ts = time.time() if now is None else now
        if self._access is None or ts >= self._access_expires_at - _ACCESS_REFRESH_SKEW_S:
            return None
        return self._access

    def refresh_token(self, *, now: float | None = None) -> str | None:
        ts = time.time() if now is None else now
        if self._refresh is None or ts >= self._refresh_expires_at:
            return None
        return self._refresh

    def clear(self) -> None:
        self._access = None
        self._refresh = None
        self._access_expires_at = 0.0
        self._refresh_expires_at = 0.0
        if self.path is not None and self.path.exists():
            self.path.unlink()

    def _save(self) -> None:
        assert self.path is not None  # noqa: S101 — invariant guarded by callers
        payload = {
            "access": self._access,
            "refresh": self._refresh,
            "access_expires_at": self._access_expires_at,
            "refresh_expires_at": self._refresh_expires_at,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 0o600 — refresh tokens are 30-day credentials.
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(payload, f)
        self.path.chmod(0o600)

    def _load(self) -> None:
        assert self.path is not None  # noqa: S101
        with self.path.open(encoding="utf-8") as f:
            payload = json.load(f)
        self._access = payload.get("access")
        self._refresh = payload.get("refresh")
        self._access_expires_at = float(payload.get("access_expires_at", 0.0))
        self._refresh_expires_at = float(payload.get("refresh_expires_at", 0.0))


class Client:
    """Sync GoCardless Bank Account Data client.

    Provide ``transport`` (``httpx.MockTransport``) in tests to stub the
    API without monkey-patching anything.
    """

    def __init__(
        self,
        secret_id: str,
        secret_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        cache: TokenCache | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._secret_id = secret_id
        self._secret_key = secret_key
        self._cache = cache if cache is not None else TokenCache()
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"Accept": "application/json", "User-Agent": "penge-gocardless/0.0"},
            transport=transport,
        )

    # ---------------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---------------------------------------------------------------
    # Token plumbing
    # ---------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        *,
        cache_path: Path | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> Client:
        """Build a client from ``GOCARDLESS_SECRET_ID`` /
        ``GOCARDLESS_SECRET_KEY`` env vars. Optional cache path picked
        up from ``GOCARDLESS_TOKEN_CACHE`` if not passed explicitly."""
        secret_id = os.environ["GOCARDLESS_SECRET_ID"]
        secret_key = os.environ["GOCARDLESS_SECRET_KEY"]
        if cache_path is None and (env_path := os.environ.get("GOCARDLESS_TOKEN_CACHE")):
            cache_path = Path(env_path)
        cache = TokenCache(path=cache_path)
        return cls(secret_id, secret_key, cache=cache, transport=transport)

    def _ensure_access_token(self) -> str:
        """Return a usable access token, refreshing or re-issuing as needed."""
        if (cached := self._cache.access_token()) is not None:
            return cached
        # Try refresh first if we still have a valid refresh token.
        if (refresh := self._cache.refresh_token()) is not None:
            try:
                refreshed = self._refresh_access(refresh)
            except ClientError:
                # Refresh token revoked / expired upstream — fall through.
                self._cache.clear()
            else:
                return refreshed
        return self._issue_token()

    def _issue_token(self) -> str:
        resp = self._http.post(
            "/token/new/",
            json={"secret_id": self._secret_id, "secret_key": self._secret_key},
        )
        if resp.status_code >= 400:
            raise ClientError(resp.status_code, resp.text)
        token = Token.model_validate(resp.json())
        self._cache.store(token)
        return token.access

    def _refresh_access(self, refresh_token: str) -> str:
        resp = self._http.post("/token/refresh/", json={"refresh": refresh_token})
        if resp.status_code >= 400:
            raise ClientError(resp.status_code, resp.text)
        body = resp.json()
        access = str(body["access"])
        expires = int(body["access_expires"])
        self._cache.store_access(access, expires)
        return access

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = self._ensure_access_token()
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {token}"
        resp = self._http.request(method, path, headers=headers, **kwargs)
        if resp.status_code == 401:
            # Token might have been revoked between cache check and request.
            self._cache.clear()
            token = self._ensure_access_token()
            headers["Authorization"] = f"Bearer {token}"
            resp = self._http.request(method, path, headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise ClientError(resp.status_code, resp.text)
        return resp

    # ---------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------

    def list_institutions(self, country: str) -> list[Institution]:
        resp = self._request("GET", "/institutions/", params={"country": country})
        return [_validate(Institution, row) for row in resp.json()]

    def create_requisition(
        self,
        *,
        institution_id: str,
        redirect: str,
        reference: str,
        user_language: str | None = None,
        agreement: str | None = None,
    ) -> Requisition:
        payload: dict[str, Any] = {
            "institution_id": institution_id,
            "redirect": redirect,
            "reference": reference,
        }
        if user_language is not None:
            payload["user_language"] = user_language
        if agreement is not None:
            payload["agreement"] = agreement
        resp = self._request("POST", "/requisitions/", json=payload)
        return _validate(Requisition, resp.json())

    def get_requisition(self, requisition_id: str) -> Requisition:
        resp = self._request("GET", f"/requisitions/{requisition_id}/")
        return _validate(Requisition, resp.json())

    def get_account_balances(self, account_id: str) -> AccountBalances:
        resp = self._request("GET", f"/accounts/{account_id}/balances/")
        return _validate(AccountBalances, resp.json())

    def get_account_transactions(
        self,
        account_id: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> TransactionsPage:
        params: dict[str, str] = {}
        if date_from is not None:
            params["date_from"] = date_from
        if date_to is not None:
            params["date_to"] = date_to
        resp = self._request(
            "GET",
            f"/accounts/{account_id}/transactions/",
            params=params or None,
        )
        body = resp.json()
        # API wraps under {"transactions": {"booked": [...], "pending": [...]}}
        if "transactions" in body:
            body = body["transactions"]
        return _validate(TransactionsPage, body)

    def get_account_details(self, account_id: str) -> AccountDetails:
        resp = self._request("GET", f"/accounts/{account_id}/details/")
        return _validate(AccountDetails, resp.json())

    def iter_requisition_accounts(self, requisition_id: str) -> Iterator[str]:
        """Yield ``account_id`` strings linked to ``requisition_id``."""
        yield from self.get_requisition(requisition_id).accounts


def _validate[T](model: type[T], payload: Any) -> T:  # noqa: ANN401 — pydantic accepts any
    try:
        return model.model_validate(payload)  # type: ignore[attr-defined]
    except ValidationError as exc:  # pragma: no cover — surfaced verbatim
        raise ClientError(0, f"unparseable response: {exc}") from exc
