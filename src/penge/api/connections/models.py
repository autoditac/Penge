"""Pydantic request/response models for the connections surface.

Validated at the HTTP boundary (instructions: never hand-parse). The
response models deliberately omit raw secrets — the ``session_id`` is
never serialised to the client; only its presence/status is exposed.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class AspspOut(_Frozen):
    """One selectable Enable Banking ASPSP."""

    provider: str
    aspsp_name: str
    aspsp_country: str
    default_currency: str


class AspspListResponse(_Frozen):
    """The set of providers the deployment can connect to."""

    providers: list[AspspOut]


class LinkRequest(_Frozen):
    """Start a consent for one provider."""

    provider: str = Field(description="Penge provider slug: gls | ebank | lunar.")
    entity_name: str = Field(
        min_length=1,
        max_length=200,
        description="Canonical person the synced accounts belong to.",
    )


class LinkResponse(_Frozen):
    """Where to send the browser to obtain consent."""

    connection_id: uuid.UUID
    consent_url: str
    state: str
    valid_until: datetime


class AuthorizeRequest(_Frozen):
    """Exchange the redirect ``code`` for a stored session."""

    code: str = Field(min_length=1, description="The ?code= value from the callback.")
    state: str | None = Field(
        default=None,
        description="The ?state= value; binds the code to its pending connection.",
    )


class ConnectionAccountOut(_Frozen):
    """One authorised account on a connection (no raw uid leaks to logs)."""

    name: str | None
    iban_masked: str | None
    currency: str | None
    product: str | None


class ConnectionErrorOut(_Frozen):
    """Sanitised debug payload for a failed link/authorize/sync."""

    step: str
    status_code: int | None
    code: str | None
    message: str
    at: datetime


class ConnectionOut(_Frozen):
    """A bank connection as exposed to the UI."""

    id: uuid.UUID
    provider: str
    aspsp_name: str
    aspsp_country: str
    entity_name: str
    status: str
    valid_until: datetime | None
    accounts: list[ConnectionAccountOut]
    last_sync_at: datetime | None
    last_sync_status: str | None
    last_error: ConnectionErrorOut | None
    created_at: datetime
    updated_at: datetime


class ConnectionListResponse(_Frozen):
    """All known connections."""

    connections: list[ConnectionOut]


class SyncResponse(_Frozen):
    """Outcome of a sync run."""

    connection: ConnectionOut
    transactions: int
    holding_snapshots: int


__all__ = [
    "AspspListResponse",
    "AspspOut",
    "AuthorizeRequest",
    "ConnectionAccountOut",
    "ConnectionErrorOut",
    "ConnectionListResponse",
    "ConnectionOut",
    "LinkRequest",
    "LinkResponse",
    "SyncResponse",
]
