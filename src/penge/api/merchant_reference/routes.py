"""Local API routes for public merchant-reference status and suggestions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.engine import Engine

from penge.api.imports.engine import get_import_engine
from penge.api.merchant_reference import store
from penge.api.merchant_reference.schemas import (
    ReferenceIndexStatusOut,
    ReferenceSearchOut,
    ReferenceSuggestionOut,
)

router = APIRouter(prefix="/vendors/reference-index", tags=["merchant reference"])

_SOURCE_ATTRIBUTION = "Name Suggestion Index contributors; OpenStreetMap contributors"
_ATTRIBUTION_URL = "https://www.openstreetmap.org/copyright"
_QUERY_MAX_LENGTH = 100
_DEFAULT_SEARCH_LIMIT = 20
_MAX_SEARCH_LIMIT = 100


def get_reference_engine() -> Engine:
    """Return the write-enabled engine for the source index tables."""
    return get_import_engine()


@router.get("/status", response_model=ReferenceIndexStatusOut)
def reference_index_status(
    engine: Annotated[Engine, Depends(get_reference_engine)],
) -> ReferenceIndexStatusOut:
    """Expose active release freshness, provenance, and sanitized failures."""
    state = store.get_status(engine)
    return ReferenceIndexStatusOut(
        source_id="name-suggestion-index",
        status=state.status,
        source_version=state.source_version,
        candidate_version=state.candidate_version,
        source_url=state.source_url,
        license=state.license,
        attribution=_SOURCE_ATTRIBUTION,
        attribution_url=_ATTRIBUTION_URL,
        checksum_sha256=state.checksum_sha256,
        package_integrity=state.package_integrity,
        candidate_integrity=state.candidate_integrity,
        source_generated_at=state.source_generated_at,
        last_checked_at=state.last_checked_at,
        last_attempt_at=state.last_attempt_at,
        last_success_at=state.last_success_at,
        snapshot_started_at=state.snapshot_started_at,
        snapshot_completed_at=state.snapshot_completed_at,
        record_count=state.record_count,
        active_generation_id=state.active_generation_id,
        error_code=state.error_code,
        error_message=state.error_message,
    )


@router.get("/search", response_model=ReferenceSearchOut)
def search_reference_index(
    q: Annotated[
        str,
        Query(min_length=1, max_length=_QUERY_MAX_LENGTH, description="Local search text."),
    ],
    engine: Annotated[Engine, Depends(get_reference_engine)],
    limit: Annotated[int, Query(ge=1, le=_MAX_SEARCH_LIMIT)] = _DEFAULT_SEARCH_LIMIT,
) -> ReferenceSearchOut:
    """Search the active local reference generation; no request is sent upstream."""
    try:
        results = store.search(engine, q, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return ReferenceSearchOut(
        match_status=results.match_status,
        source_status=results.source_status,
        source_version=results.source_version,
        limit=limit,
        truncated=results.truncated,
        matches=[
            ReferenceSuggestionOut(
                source_entity_id=match.source_entity_id,
                label=match.label,
                aliases=list(match.aliases),
                category_path=match.category_path,
                wikidata_id=match.wikidata_id,
                source_version=match.source_version,
                source_url=match.source_url,
                license=match.license,
                match_kind=match.match_kind,
            )
            for match in results.matches
        ],
    )


__all__ = ["get_reference_engine", "router"]
