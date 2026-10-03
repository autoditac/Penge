"""Transactional persistence and conservative local lookup of public references."""

from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, selectinload

from penge.api.merchant_reference.store_models import (
    MerchantReference,
    MerchantReferenceAlias,
    MerchantReferenceGeneration,
    MerchantReferenceRefreshState,
)
from penge.ingest.merchant_reference.nsi import NsiRelease, NsiSnapshot

SOURCE_ID = "name-suggestion-index"
NSI_LICENSE: Literal["BSD-3-Clause"] = "BSD-3-Clause"
INITIAL_STATUS = "never_refreshed"
REFRESHING_STATUS = "refreshing"
CURRENT_STATUS = "current"
STALE_STATUS = "stale"
FAILED_STATUS = "failed"
STAGING_STATUS = "staging"
ACTIVE_STATUS = "active"
SUPERSEDED_STATUS = "superseded"
MAX_SEARCH_RESULTS = 100
REFRESH_STALE_AFTER = timedelta(hours=2)


@dataclass(frozen=True, slots=True)
class ReferenceIndexState:
    """Sanitized state of the active public-reference generation."""

    source_id: str
    status: Literal["never_refreshed", "refreshing", "current", "stale", "failed"]
    source_version: str | None
    candidate_version: str | None
    source_url: str | None
    license: Literal["BSD-3-Clause"] | None
    checksum_sha256: str | None
    package_integrity: str | None
    candidate_integrity: str | None
    source_generated_at: datetime | None
    last_checked_at: datetime | None
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    snapshot_started_at: datetime | None
    snapshot_completed_at: datetime | None
    record_count: int | None
    active_generation_id: uuid.UUID | None
    error_code: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class ReferenceMatch:
    """A public reference and the kind of local alias match it produced."""

    source_entity_id: str
    label: str
    aliases: tuple[str, ...]
    category_path: str
    wikidata_id: str | None
    source_version: str
    source_url: str
    license: Literal["BSD-3-Clause"]
    match_kind: Literal["exact_alias", "substring"]


@dataclass(frozen=True, slots=True)
class ReferenceSearch:
    """Local reference results, preserving ambiguous name collisions."""

    match_status: Literal["no_match", "unique", "ambiguous"]
    source_status: Literal["never_refreshed", "refreshing", "current", "stale", "failed"]
    source_version: str | None
    matches: tuple[ReferenceMatch, ...]
    truncated: bool


def get_status(engine: Engine, *, now: datetime | None = None) -> ReferenceIndexState:
    """Read current generation metadata without exposing private aliases."""
    with Session(engine) as session:
        state = session.get(MerchantReferenceRefreshState, SOURCE_ID)
        if state is None:
            return _empty_status()
        generation = (
            session.get(MerchantReferenceGeneration, state.active_generation_id)
            if state.active_generation_id is not None
            else None
        )
        status = _effective_status(state, now=_utc_now(now))
        return ReferenceIndexState(
            source_id=SOURCE_ID,
            status=status,
            source_version=generation.source_version if generation is not None else None,
            candidate_version=state.candidate_version,
            source_url=generation.source_url if generation is not None else None,
            license=(_known_license(generation.license) if generation is not None else None),
            checksum_sha256=generation.catalog_sha256 if generation is not None else None,
            package_integrity=generation.package_integrity if generation is not None else None,
            candidate_integrity=state.candidate_integrity,
            source_generated_at=generation.source_generated_at if generation is not None else None,
            last_checked_at=state.last_checked_at,
            last_attempt_at=state.last_attempt_at,
            last_success_at=state.last_success_at,
            snapshot_started_at=state.snapshot_started_at,
            snapshot_completed_at=state.snapshot_completed_at,
            record_count=generation.record_count if generation is not None else None,
            active_generation_id=state.active_generation_id,
            error_code=state.error_code,
            error_message=state.error_message,
        )


def mark_refresh_started(engine: Engine, *, now: datetime | None = None) -> None:
    """Persist the start of a release check while retaining the active generation."""
    started = _utc_now(now)
    with Session(engine) as session, session.begin():
        state = session.get(MerchantReferenceRefreshState, SOURCE_ID)
        if state is None:
            state = MerchantReferenceRefreshState(
                source_id=SOURCE_ID,
                status=REFRESHING_STATUS,
                last_attempt_at=started,
                snapshot_started_at=started,
            )
            session.add(state)
        else:
            state.status = REFRESHING_STATUS
            state.candidate_version = None
            state.candidate_integrity = None
            state.last_attempt_at = started
            state.snapshot_started_at = started
            state.error_code = None
            state.error_message = None


def mark_candidate_release(
    engine: Engine,
    release: NsiRelease,
    *,
    now: datetime | None = None,
) -> None:
    """Record the exact candidate package release before downloading its catalog."""
    at = _utc_now(now)
    with Session(engine) as session, session.begin():
        state = _state_for_update(session)
        state.candidate_version = release.version
        state.candidate_integrity = release.integrity
        state.last_checked_at = at


def mark_unchanged(engine: Engine, *, now: datetime | None = None) -> None:
    """Record a successful check when the latest package matches the active version."""
    checked = _utc_now(now)
    with Session(engine) as session, session.begin():
        state = _state_for_update(session)
        state.status = CURRENT_STATUS
        state.candidate_version = None
        state.candidate_integrity = None
        state.last_checked_at = checked
        state.error_code = None
        state.error_message = None


def mark_failure(
    engine: Engine,
    *,
    error_code: str,
    error_message: str,
    now: datetime | None = None,
) -> None:
    """Keep the last valid index active and expose a sanitized failed/stale state."""
    failed_at = _utc_now(now)
    with Session(engine) as session, session.begin():
        state = _state_for_update(session)
        state.status = STALE_STATUS if state.active_generation_id is not None else FAILED_STATUS
        state.last_checked_at = failed_at
        state.error_code = error_code[:64]
        state.error_message = error_message[:1000]


def promote_snapshot(
    engine: Engine,
    snapshot: NsiSnapshot,
    release: NsiRelease,
    *,
    now: datetime | None = None,
) -> uuid.UUID:
    """Atomically store a validated full snapshot and switch the active pointer."""
    completed = _utc_now(now)
    generation_id = uuid.uuid4()
    with Session(engine) as session, session.begin():
        state = _state_for_update(session)
        generation = MerchantReferenceGeneration(
            id=generation_id,
            source_id=SOURCE_ID,
            source_version=snapshot.source_version,
            package_integrity=release.integrity,
            catalog_sha256=snapshot.sha256,
            source_generated_at=snapshot.source_generated_at,
            retrieved_at=snapshot.retrieved_at,
            source_url=snapshot.source_url,
            license=snapshot.license,
            record_count=snapshot.record_count,
            status=ACTIVE_STATUS,
            completed_at=completed,
        )
        session.add(generation)

        references: list[MerchantReference] = []
        aliases: list[MerchantReferenceAlias] = []
        for public_reference in snapshot.records:
            reference_id = uuid.uuid4()
            references.append(
                MerchantReference(
                    id=reference_id,
                    generation_id=generation_id,
                    source_id=public_reference.source_id,
                    source_entity_id=public_reference.source_entity_id,
                    label=public_reference.label,
                    category_path=public_reference.category_path,
                    wikidata_id=public_reference.wikidata_id,
                    source_version=public_reference.source_version,
                    source_revision_at=public_reference.source_revision_at,
                    source_url=public_reference.source_url,
                    license=public_reference.license,
                )
            )
            seen_aliases: set[str] = set()
            for alias in public_reference.aliases:
                normalized = normalize_alias(alias)
                if not normalized or normalized in seen_aliases:
                    continue
                seen_aliases.add(normalized)
                aliases.append(
                    MerchantReferenceAlias(
                        id=uuid.uuid4(),
                        generation_id=generation_id,
                        reference_id=reference_id,
                        alias=alias,
                        normalized_alias=normalized,
                    )
                )
        session.add_all(references)
        session.add_all(aliases)

        previous_generation_id = state.active_generation_id
        if previous_generation_id is not None:
            previous = session.get(MerchantReferenceGeneration, previous_generation_id)
            if previous is not None:
                previous.status = SUPERSEDED_STATUS

        state.status = CURRENT_STATUS
        state.active_generation_id = generation_id
        state.candidate_version = None
        state.candidate_integrity = None
        state.last_checked_at = completed
        state.last_success_at = completed
        state.snapshot_completed_at = completed
        state.error_code = None
        state.error_message = None

        superseded_generations = session.scalars(
            select(MerchantReferenceGeneration)
            .where(
                MerchantReferenceGeneration.source_id == SOURCE_ID,
                MerchantReferenceGeneration.status == SUPERSEDED_STATUS,
                MerchantReferenceGeneration.id != previous_generation_id,
            )
            .options(
                selectinload(MerchantReferenceGeneration.references).selectinload(
                    MerchantReference.aliases
                )
            )
        )
        for superseded in superseded_generations:
            session.delete(superseded)

    return generation_id


def search(
    engine: Engine,
    query: str,
    *,
    limit: int = 20,
) -> ReferenceSearch:
    """Find exact or substring matches locally without outbound lookups."""
    if not 1 <= limit <= MAX_SEARCH_RESULTS:
        raise ValueError(f"limit must be between 1 and {MAX_SEARCH_RESULTS}")
    normalized_query = normalize_alias(query)
    if not any(character.isalnum() for character in normalized_query):
        raise ValueError("query must contain at least one letter or number")

    with Session(engine) as session:
        state = session.get(MerchantReferenceRefreshState, SOURCE_ID)
        if state is None:
            return ReferenceSearch(
                match_status="no_match",
                source_status="never_refreshed",
                source_version=None,
                matches=(),
                truncated=False,
            )
        generation = (
            session.get(MerchantReferenceGeneration, state.active_generation_id)
            if state.active_generation_id is not None
            else None
        )
        source_status = _effective_status(state, now=datetime.now(UTC))
        if generation is None:
            return ReferenceSearch(
                match_status="no_match",
                source_status=source_status,
                source_version=None,
                matches=(),
                truncated=False,
            )

        references = _search_references(
            session,
            generation_id=generation.id,
            search_value=normalized_query,
            exact=True,
            limit=limit + 1,
        )
        has_more = len(references) > limit
        references = references[:limit]
        match_kind: Literal["exact_alias", "substring"] = "exact_alias"
        if not references:
            references = _search_references(
                session,
                generation_id=generation.id,
                search_value=_escape_like(normalized_query),
                exact=False,
                limit=limit + 1,
            )
            has_more = len(references) > limit
            references = references[:limit]
            match_kind = "substring"

        matches = tuple(
            ReferenceMatch(
                source_entity_id=reference.source_entity_id,
                label=reference.label,
                aliases=tuple(alias.alias for alias in reference.aliases),
                category_path=reference.category_path,
                wikidata_id=reference.wikidata_id,
                source_version=reference.source_version,
                source_url=reference.source_url,
                license=_known_license(reference.license),
                match_kind=match_kind,
            )
            for reference in references
        )
        if not matches:
            match_status: Literal["no_match", "unique", "ambiguous"] = "no_match"
        elif len(matches) == 1 and not has_more:
            match_status = "unique"
        else:
            match_status = "ambiguous"
        return ReferenceSearch(
            match_status=match_status,
            source_status=source_status,
            source_version=generation.source_version,
            matches=matches,
            truncated=has_more,
        )


def normalize_alias(value: str) -> str:
    """Normalize literal aliases without removing punctuation or guessing identity."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _search_references(
    session: Session,
    *,
    generation_id: uuid.UUID,
    search_value: str,
    exact: bool,
    limit: int,
) -> list[MerchantReference]:
    condition = (
        MerchantReferenceAlias.normalized_alias == search_value
        if exact
        else MerchantReferenceAlias.normalized_alias.like(f"%{search_value}%", escape="\\")
    )
    statement = (
        select(MerchantReference)
        .join(MerchantReferenceAlias)
        .where(
            MerchantReference.generation_id == generation_id,
            MerchantReferenceAlias.generation_id == generation_id,
            condition,
        )
        .options(selectinload(MerchantReference.aliases))
        .distinct()
        .order_by(MerchantReference.label, MerchantReference.source_entity_id)
        .limit(limit)
    )
    return list(session.scalars(statement).unique())


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _state_for_update(session: Session) -> MerchantReferenceRefreshState:
    state = session.get(MerchantReferenceRefreshState, SOURCE_ID)
    if state is None:
        state = MerchantReferenceRefreshState(
            source_id=SOURCE_ID,
            status=REFRESHING_STATUS,
        )
        session.add(state)
        session.flush()
    return state


def _empty_status() -> ReferenceIndexState:
    return ReferenceIndexState(
        source_id=SOURCE_ID,
        status="never_refreshed",
        source_version=None,
        candidate_version=None,
        source_url=None,
        license=None,
        checksum_sha256=None,
        package_integrity=None,
        candidate_integrity=None,
        source_generated_at=None,
        last_checked_at=None,
        last_attempt_at=None,
        last_success_at=None,
        snapshot_started_at=None,
        snapshot_completed_at=None,
        record_count=None,
        active_generation_id=None,
        error_code=None,
        error_message=None,
    )


def _known_status(
    value: str,
) -> Literal["never_refreshed", "refreshing", "current", "stale", "failed"]:
    if value == INITIAL_STATUS:
        return "never_refreshed"
    if value == REFRESHING_STATUS:
        return "refreshing"
    if value == CURRENT_STATUS:
        return "current"
    if value == STALE_STATUS:
        return "stale"
    if value == FAILED_STATUS:
        return "failed"
    raise ValueError(f"unknown public-reference status: {value}")


def _effective_status(
    state: MerchantReferenceRefreshState,
    *,
    now: datetime,
) -> Literal["never_refreshed", "refreshing", "current", "stale", "failed"]:
    status = _known_status(state.status)
    if (
        status == REFRESHING_STATUS
        and state.last_attempt_at is not None
        and now - _stored_utc(state.last_attempt_at) >= REFRESH_STALE_AFTER
    ):
        return "stale" if state.active_generation_id is not None else "failed"
    return status


def _known_license(value: str) -> Literal["BSD-3-Clause"]:
    if value != NSI_LICENSE:
        raise ValueError("public reference storage contains an unknown license")
    return NSI_LICENSE


def _utc_now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return current.astimezone(UTC)


def _stored_utc(value: datetime) -> datetime:
    """Normalize timestamps returned by SQLite test databases as UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
