"""Enable Banking HTTP client.

Sync-only (we have no concurrent need today; httpx.Client is plenty
fast for personal-finance loads). Authentication is an RS256 JWT
re-signed lazily when the previous token is within ~60s of expiry.
The private key never leaves the process.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import jwt as pyjwt
from pydantic import BaseModel

from .models import (
    AuthorizeSessionResponse,
    BalancesResponse,
    GetSessionResponse,
    StartAuthorizationResponse,
    TransactionsResponse,
)

log = logging.getLogger("penge.ingest.enablebanking")

DEFAULT_BASE_URL = "https://api.enablebanking.com"
JWT_LIFETIME_SECONDS = 3600  # 1h; max allowed is 86400
JWT_REFRESH_LEEWAY_SECONDS = 60

_HTTP_NO_CONTENT = 204
_HTTP_BAD_REQUEST = 400


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ClientConfig:
    """Static configuration for the Enable Banking client.

    Use :meth:`from_env` to populate from process environment for the
    CLI / scripts; tests construct ``ClientConfig`` directly.
    """

    application_id: str  # the ``kid`` in the JWT header
    private_key_pem: str  # full ``-----BEGIN RSA PRIVATE KEY-----`` body
    base_url: str = DEFAULT_BASE_URL

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> ClientConfig:
        env = env if env is not None else dict(os.environ)
        try:
            app_id = env["ENABLEBANKING_APPLICATION_ID"]
            key_path = env["ENABLEBANKING_KEY_PATH"]
        except KeyError as missing:  # pragma: no cover - explicit user error
            raise RuntimeError(
                "ENABLEBANKING_APPLICATION_ID and ENABLEBANKING_KEY_PATH "
                "must be set in the environment"
            ) from missing
        pem = Path(key_path).expanduser().read_text(encoding="utf-8")
        base_url = env.get("ENABLEBANKING_BASE_URL", DEFAULT_BASE_URL)
        return cls(application_id=app_id, private_key_pem=pem, base_url=base_url)


# --------------------------------------------------------------------------- #
# Token cache
# --------------------------------------------------------------------------- #


@dataclass
class _TokenCache:
    token: str | None = field(default=None)
    exp_at: float = field(default=0.0)


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #


class EnableBankingError(RuntimeError):
    """Raised when the API returns a non-2xx status."""

    def __init__(self, status_code: int, body: Any) -> None:
        super().__init__(f"Enable Banking API error {status_code}: {body!r}")
        self.status_code = status_code
        self.body = body


class Client:
    """Thin wrapper around the Enable Banking REST API.

    Construct with an explicit :class:`ClientConfig` or via
    :meth:`from_env`. The client owns an ``httpx.Client`` for
    connection pooling and is safe to use as a context manager.
    """

    def __init__(
        self,
        config: ClientConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._config = config
        self._cache = _TokenCache()
        self._http = httpx.Client(
            base_url=config.base_url,
            transport=transport,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    @classmethod
    def from_env(
        cls,
        env: dict[str, str] | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> Client:
        return cls(ClientConfig.from_env(env), transport=transport)

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------ #
    # JWT
    # ------------------------------------------------------------------ #

    def _ensure_jwt(self) -> str:
        now = time.time()
        if self._cache.token and now < self._cache.exp_at - JWT_REFRESH_LEEWAY_SECONDS:
            return self._cache.token
        iat = int(now)
        exp = iat + JWT_LIFETIME_SECONDS
        payload = {
            "iss": "enablebanking.com",
            "aud": "api.enablebanking.com",
            "iat": iat,
            "exp": exp,
        }
        token = pyjwt.encode(
            payload,
            self._config.private_key_pem,
            algorithm="RS256",
            headers={"typ": "JWT", "kid": self._config.application_id},
        )
        self._cache.token = token
        self._cache.exp_at = float(exp)
        return token

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._ensure_jwt()}"}

    # ------------------------------------------------------------------ #
    # Low-level request
    # ------------------------------------------------------------------ #

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        resp = self._http.request(
            method,
            path,
            json=json,
            params={k: v for k, v in (params or {}).items() if v is not None},
            headers=self._auth_headers(),
        )
        if resp.status_code >= _HTTP_BAD_REQUEST:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise EnableBankingError(resp.status_code, body)
        if resp.status_code == _HTTP_NO_CONTENT or not resp.content:
            return None
        return resp.json()

    @staticmethod
    def _parse[T: BaseModel](model: type[T], payload: Any) -> T:
        return model.model_validate(payload)

    # ------------------------------------------------------------------ #
    # AIS endpoints
    # ------------------------------------------------------------------ #

    def start_authorization(
        self,
        *,
        aspsp_name: str,
        aspsp_country: str,
        redirect_url: str,
        valid_until: datetime,
        psu_type: str = "personal",
        state: str | None = None,
        balances: bool = True,
        transactions: bool = True,
    ) -> StartAuthorizationResponse:
        """``POST /auth`` — start consent for an ASPSP.

        ``valid_until`` becomes the consent expiry; cap at the
        ``maximum_consent_validity`` advertised by the ASPSP (commonly
        180 days for retail).
        """
        body = {
            "access": {
                "valid_until": valid_until.astimezone(UTC).isoformat(),
                "balances": balances,
                "transactions": transactions,
            },
            "aspsp": {"name": aspsp_name, "country": aspsp_country},
            "state": state or str(uuid.uuid4()),
            "redirect_url": redirect_url,
            "psu_type": psu_type,
        }
        return self._parse(StartAuthorizationResponse, self._request("POST", "/auth", json=body))

    def authorize_session(self, code: str) -> AuthorizeSessionResponse:
        """``POST /sessions`` — exchange the redirect ``code`` for a session."""
        return self._parse(
            AuthorizeSessionResponse,
            self._request("POST", "/sessions", json={"code": code}),
        )

    def get_session(self, session_id: str) -> GetSessionResponse:
        """``GET /sessions/{id}``."""
        return self._parse(
            GetSessionResponse, self._request("GET", f"/sessions/{session_id}")
        )

    def get_account_balances(self, account_uid: str) -> BalancesResponse:
        """``GET /accounts/{uid}/balances``."""
        return self._parse(
            BalancesResponse,
            self._request("GET", f"/accounts/{account_uid}/balances"),
        )

    def get_account_transactions(
        self,
        account_uid: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        transaction_status: str = "BOOK",
        strategy: str | None = None,
    ) -> TransactionsResponse:
        """``GET /accounts/{uid}/transactions`` with auto-pagination.

        Aggregates pages following ``continuation_key`` so callers get
        a single ``TransactionsResponse`` with the full slice.
        """
        all_txns = []
        continuation_key: str | None = None
        while True:
            params: dict[str, Any] = {
                "date_from": date_from,
                "date_to": date_to,
                "transaction_status": transaction_status,
                "strategy": strategy,
                "continuation_key": continuation_key,
            }
            page = self._parse(
                TransactionsResponse,
                self._request(
                    "GET",
                    f"/accounts/{account_uid}/transactions",
                    params=params,
                ),
            )
            all_txns.extend(page.transactions)
            if not page.continuation_key:
                break
            continuation_key = page.continuation_key
        return TransactionsResponse(transactions=all_txns, continuation_key=None)

    # ------------------------------------------------------------------ #
    # Misc
    # ------------------------------------------------------------------ #

    def get_aspsps(self, *, country: str | None = None) -> Any:
        """``GET /aspsps`` — raw JSON, no model (rarely used)."""
        return self._request("GET", "/aspsps", params={"country": country})


__all__ = ["Client", "ClientConfig", "EnableBankingError"]


# Default consent validity helper for callers that don't want to do
# ``datetime`` math themselves. 180 days matches the retail max for
# most German ASPSPs (GLS, Evangelische Bank, etc.).
def default_consent_until(days: int = 180) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)
