"""Guarded corrections to bank account metadata.

An account's owner may differ from the owner of its Enable Banking consent.
The override is stored on the canonical account so repeat syncs cannot undo it.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import MetaData, Table, func, select
from sqlalchemy.engine import Engine

from penge.api.connections.config import ConnectionsConfig
from penge.api.connections.routes import get_engine, require_enabled
from penge.ops.net_worth_refresh import (
    LockUnavailableError,
    RefreshStateError,
    refresh_write_intent,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])


class AccountMetadataPatch(BaseModel):
    """A deliberate, per-account correction (not a connection-wide owner)."""

    model_config = ConfigDict(extra="forbid")

    entity_id: uuid.UUID | None = None
    kind: Literal["checking", "savings"] | None = None

    @model_validator(mode="after")
    def require_correction(self) -> AccountMetadataPatch:
        """Reject empty patches and nulls instead of silently resetting overrides."""
        if not self.model_fields_set or any(
            getattr(self, field) is None for field in self.model_fields_set
        ):
            raise ValueError("provide a non-null entity_id and/or kind")
        return self


class AccountMetadataOut(BaseModel):
    """The effective metadata after a correction; never includes an IBAN."""

    model_config = ConfigDict(frozen=True)

    account_id: uuid.UUID
    entity_id: uuid.UUID
    kind: str


@router.patch("/{account_id}/metadata", response_model=AccountMetadataOut)
def correct_account_metadata(
    account_id: uuid.UUID,
    body: AccountMetadataPatch,
    config: Annotated[ConnectionsConfig, Depends(require_enabled)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> AccountMetadataOut:
    """Override owner and/or kind for an existing Enable Banking account."""
    try:
        with refresh_write_intent(
            lock_file=config.refresh_state_dir / "refresh.lock",
            pending_refresh_file=config.refresh_state_dir / "pending",
        ) as observe_write:
            metadata = MetaData()
            account = Table("account", metadata, autoload_with=engine)
            entity = Table("entity", metadata, autoload_with=engine)
            with engine.begin() as conn:
                existing = (
                    conn.execute(
                        select(account).where(account.c.id == account_id).with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is None or existing["provider"] not in ("gls", "ebank", "lunar"):
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="bank account not found",
                    )
                if body.entity_id is not None:
                    owner = conn.execute(
                        select(entity.c.id).where(
                            entity.c.id == body.entity_id, entity.c.kind == "person"
                        )
                    ).scalar_one_or_none()
                    if owner is None:
                        raise HTTPException(
                            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="owner must be an existing person",
                        )

                values: dict[str, object] = {}
                if body.entity_id is not None:
                    values["entity_id"] = body.entity_id
                    values["entity_override_id"] = body.entity_id
                if body.kind is not None:
                    values["kind"] = body.kind
                    values["kind_override"] = body.kind
                changed = any(existing[key] != value for key, value in values.items())
                if changed:
                    values["updated_at"] = func.now()
                    conn.execute(
                        account.update().where(account.c.id == account_id).values(**values)
                    )
            if changed:
                observe_write(1)
            return AccountMetadataOut(
                account_id=account_id,
                entity_id=body.entity_id or existing["entity_id"],
                kind=body.kind or existing["kind"],
            )
    except (LockUnavailableError, RefreshStateError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


__all__ = ["router"]
