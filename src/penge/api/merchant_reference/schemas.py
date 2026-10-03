"""Public merchant-reference status and local-search response models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReferenceIndexStatusOut(BaseModel):
    """Refresh status, active provenance, and sanitized failure information."""

    model_config = ConfigDict(extra="forbid")

    source_id: Literal["name-suggestion-index"] = "name-suggestion-index"
    status: Literal["never_refreshed", "refreshing", "current", "stale", "failed"]
    source_version: str | None
    candidate_version: str | None
    source_url: str | None
    license: Literal["BSD-3-Clause"] | None
    attribution: str
    attribution_url: str
    checksum_sha256: str | None
    package_integrity: str | None
    candidate_integrity: str | None
    source_generated_at: datetime | None
    last_checked_at: datetime | None
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    snapshot_started_at: datetime | None
    snapshot_completed_at: datetime | None
    record_count: int | None = Field(default=None, ge=0)
    active_generation_id: uuid.UUID | None
    error_code: str | None
    error_message: str | None


class ReferenceSuggestionOut(BaseModel):
    """One public reference search result with its source provenance."""

    model_config = ConfigDict(extra="forbid")

    source_entity_id: str
    label: str
    aliases: list[str]
    category_path: str
    wikidata_id: str | None
    source_version: str
    source_url: str
    license: Literal["BSD-3-Clause"]
    match_kind: Literal["exact_alias", "substring"]


class ReferenceSearchOut(BaseModel):
    """Conservative local-only matches for a user-provided search string."""

    model_config = ConfigDict(extra="forbid")

    match_status: Literal["no_match", "unique", "ambiguous"]
    source_status: Literal["never_refreshed", "refreshing", "current", "stale", "failed"]
    source_version: str | None
    matches: list[ReferenceSuggestionOut]
    limit: int = Field(ge=1, le=100)
    truncated: bool


class ReferenceRefreshOut(BaseModel):
    """Machine-readable summary of one scheduled source refresh."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["current", "stale", "failed"]
    source_version: str | None
    records_promoted: int = Field(ge=0)
    skipped_unchanged: bool
    error_code: str | None = None
