"""Route handlers for the in-app Enable Banking consent flow (ADR-0040).

A second write surface alongside ``/imports``. Endpoints are gated on
:class:`ConnectionsConfig.enabled` (the EB signing key must be present
in the API process) and return HTTP 503 otherwise, so the read-only
deployments are unaffected. Secrets never reach the client: the stored
``session_id`` is not serialised, only its status.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.engine import Engine

from penge.api.connections import service, store
from penge.api.connections.config import ConnectionsConfig
from penge.api.connections.models import (
    AspspListResponse,
    AspspOut,
    AuthorizeRequest,
    ConnectionAccountOut,
    ConnectionErrorOut,
    ConnectionListResponse,
    ConnectionOut,
    LinkRequest,
    LinkResponse,
    SyncResponse,
)
from penge.api.connections.provider import all_providers
from penge.api.imports.engine import get_import_engine
from penge.ingest.enablebanking.client import Client

if TYPE_CHECKING:
    from collections.abc import Iterator

log = logging.getLogger("penge.api.connections")

router = APIRouter(prefix="/connections", tags=["connections"])

_HISTORY_MIN = 1
_HISTORY_MAX = 1095


# --------------------------------------------------------------------------- #
# Dependencies (overridable in tests)
# --------------------------------------------------------------------------- #


def get_config() -> ConnectionsConfig:
    """Resolve the connections feature configuration from the environment."""
    return ConnectionsConfig.from_env()


def require_enabled(
    config: Annotated[ConnectionsConfig, Depends(get_config)],
) -> ConnectionsConfig:
    """Reject requests when the EB signing key is not configured."""
    if not config.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Bank connections are disabled: no Enable Banking signing key is "
                "configured in this deployment."
            ),
        )
    return config


def get_engine() -> Engine:
    """Return the write-enabled engine (shared with the imports surface)."""
    return get_import_engine()


def get_client(
    config: Annotated[ConnectionsConfig, Depends(require_enabled)],
) -> Iterator[Client]:
    """Build an Enable Banking client for the duration of one request."""
    _ = config
    client = Client.from_env()
    try:
        yield client
    finally:
        client.close()


# --------------------------------------------------------------------------- #
# Mapping helpers
# --------------------------------------------------------------------------- #


def _error_out(payload: dict[str, object] | None) -> ConnectionErrorOut | None:
    if not payload:
        return None
    raw_at = payload.get("at")
    at = datetime.fromisoformat(raw_at) if isinstance(raw_at, str) else datetime.now(UTC)
    status_code = payload.get("status_code")
    code = payload.get("code")
    return ConnectionErrorOut(
        step=str(payload.get("step", "unknown")),
        status_code=status_code if isinstance(status_code, int) else None,
        code=str(code) if isinstance(code, str) else None,
        message=str(payload.get("message", "")),
        at=at,
    )


def _account_out(raw: dict[str, object]) -> ConnectionAccountOut:
    def _str_or_none(key: str) -> str | None:
        value = raw.get(key)
        return value if isinstance(value, str) else None

    return ConnectionAccountOut(
        name=_str_or_none("name"),
        iban_masked=_str_or_none("iban_masked"),
        currency=_str_or_none("currency"),
        product=_str_or_none("product"),
    )


def _connection_out(record: store.ConnectionRecord) -> ConnectionOut:
    return ConnectionOut(
        id=record.id,
        provider=record.provider,
        aspsp_name=record.aspsp_name,
        aspsp_country=record.aspsp_country,
        entity_name=record.entity_name,
        status=record.status,
        valid_until=record.valid_until,
        accounts=[_account_out(a) for a in record.accounts],
        last_sync_at=record.last_sync_at,
        last_sync_status=record.last_sync_status,
        last_error=_error_out(record.last_error),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _raise_for(error: service.ConnectionError) -> HTTPException:
    if error.not_found:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error.message)
    # Upstream (Enable Banking) failures surface as 502 so the client can
    # distinguish them from its own bad request.
    code = status.HTTP_502_BAD_GATEWAY if error.status_code else status.HTTP_400_BAD_REQUEST
    detail = error.message
    if error.code:
        detail = f"{error.code}: {error.message}"
    return HTTPException(status_code=code, detail=detail)


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.get("/aspsps", response_model=AspspListResponse)
def list_aspsps(
    _: Annotated[ConnectionsConfig, Depends(require_enabled)],
) -> AspspListResponse:
    """List the Enable Banking ASPSPs this deployment can connect to."""
    return AspspListResponse(
        providers=[
            AspspOut(
                provider=p.slug,
                aspsp_name=p.aspsp_name,
                aspsp_country=p.aspsp_country,
                default_currency=p.default_currency,
            )
            for p in all_providers()
        ]
    )


@router.get("", response_model=ConnectionListResponse)
def list_connections_route(
    _: Annotated[ConnectionsConfig, Depends(require_enabled)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ConnectionListResponse:
    """List every bank connection with its status and last-sync debug info."""
    records = store.list_connections(engine)
    return ConnectionListResponse(connections=[_connection_out(r) for r in records])


@router.post("/link", response_model=LinkResponse)
def link_route(
    body: LinkRequest,
    config: Annotated[ConnectionsConfig, Depends(require_enabled)],
    engine: Annotated[Engine, Depends(get_engine)],
    client: Annotated[Client, Depends(get_client)],
) -> LinkResponse:
    """Start a consent and return the bank's consent URL."""
    try:
        record, consent_url = service.start_link(
            engine,
            client,
            redirect_url=config.redirect_url,
            provider_slug=body.provider,
            entity_name=body.entity_name,
        )
    except service.ConnectionError as exc:
        raise _raise_for(exc) from exc
    assert record.state is not None  # noqa: S101 - just inserted as 'linking'
    assert record.valid_until is not None  # noqa: S101
    return LinkResponse(
        connection_id=record.id,
        consent_url=consent_url,
        state=record.state,
        valid_until=record.valid_until,
    )


@router.post("/authorize", response_model=ConnectionOut)
def authorize_route(
    body: AuthorizeRequest,
    _: Annotated[ConnectionsConfig, Depends(require_enabled)],
    engine: Annotated[Engine, Depends(get_engine)],
    client: Annotated[Client, Depends(get_client)],
) -> ConnectionOut:
    """Exchange the redirect code for a stored session."""
    try:
        record = service.authorize(engine, client, code=body.code, state=body.state)
    except service.ConnectionError as exc:
        raise _raise_for(exc) from exc
    return _connection_out(record)


@router.post("/{connection_id}/sync", response_model=SyncResponse)
def sync_route(
    connection_id: uuid.UUID,
    _: Annotated[ConnectionsConfig, Depends(require_enabled)],
    engine: Annotated[Engine, Depends(get_engine)],
    client: Annotated[Client, Depends(get_client)],
    days: Annotated[int, Query(ge=_HISTORY_MIN, le=_HISTORY_MAX)] = service.DEFAULT_HISTORY_DAYS,
) -> SyncResponse:
    """Pull transactions + balances for one connection into Postgres."""
    try:
        outcome = service.sync(engine, client, connection_id=connection_id, days=days)
    except service.ConnectionError as exc:
        raise _raise_for(exc) from exc
    return SyncResponse(
        connection=_connection_out(outcome.record),
        transactions=outcome.transactions,
        holding_snapshots=outcome.holding_snapshots,
    )


__all__ = ["router"]
