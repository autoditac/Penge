"""Scheduled refresh orchestration for the public merchant-reference index."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from penge.api.merchant_reference import store
from penge.ingest.merchant_reference.nsi import NsiRelease, NsiSnapshot, NsiSourceError

log = logging.getLogger("penge.api.merchant_reference")


class SnapshotClient(Protocol):
    """Typed network boundary for a versioned public catalog."""

    def discover_release(self) -> NsiRelease: ...

    def fetch_snapshot(self, release: NsiRelease | None = None) -> NsiSnapshot: ...


class ReferenceStoreError(RuntimeError):
    """Raised when a validated candidate cannot be safely persisted."""


@dataclass(frozen=True, slots=True)
class RefreshResult:
    """Sanitized result of one scheduled source check."""

    status: str
    source_version: str | None
    records_promoted: int
    skipped_unchanged: bool
    error_code: str | None = None

    def to_json(self) -> str:
        """Serialize the safe worker result."""
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    @property
    def ok(self) -> bool:
        """Return whether the index is current after this source check."""
        return self.status == "current" and self.error_code is None


def refresh_index(
    engine: Engine,
    client: SnapshotClient,
    *,
    now: datetime | None = None,
) -> RefreshResult:
    """Discover and validate a release, then atomically promote its snapshot."""
    started = _as_utc(now or datetime.now(UTC))
    store.mark_refresh_started(engine, now=started)
    candidate_version: str | None = None
    try:
        release = client.discover_release()
        candidate_version = release.version
        current = store.get_status(engine)
        store.mark_candidate_release(engine, release, now=started)
        if (
            current.source_version == release.version
            and current.package_integrity == release.integrity
            and current.active_generation_id is not None
        ):
            store.mark_unchanged(engine, now=_completion_time(now))
            return RefreshResult(
                status="current",
                source_version=release.version,
                records_promoted=0,
                skipped_unchanged=True,
            )

        snapshot = client.fetch_snapshot(release)
        store.promote_snapshot(
            engine,
            snapshot,
            release,
            now=_completion_time(now),
        )
    except NsiSourceError as exc:
        completion = _completion_time(now)
        store.mark_failure(
            engine,
            error_code=exc.code,
            error_message=exc.message,
            now=completion,
        )
        failed_status = store.get_status(engine)
        log.error("public_reference_refresh_failed code=%s", exc.code)
        return RefreshResult(
            status=failed_status.status,
            source_version=failed_status.source_version or candidate_version,
            records_promoted=0,
            skipped_unchanged=False,
            error_code=exc.code,
        )
    except SQLAlchemyError as exc:
        completion = _completion_time(now)
        store.mark_failure(
            engine,
            error_code="database_write_failed",
            error_message="The validated public index could not be committed.",
            now=completion,
        )
        log.error("public_reference_refresh_persistence_failed code=%s", type(exc).__name__)
        raise ReferenceStoreError("The validated public index could not be committed.") from exc

    return RefreshResult(
        status="current",
        source_version=snapshot.source_version,
        records_promoted=snapshot.record_count,
        skipped_unchanged=False,
    )


def preview_release(engine: Engine, client: SnapshotClient) -> RefreshResult:
    """Check the public release without changing database or refresh state."""
    try:
        release = client.discover_release()
    except NsiSourceError as exc:
        state = store.get_status(engine)
        log.error("public_reference_refresh_preview_failed code=%s", exc.code)
        return RefreshResult(
            status=state.status,
            source_version=state.source_version,
            records_promoted=0,
            skipped_unchanged=False,
            error_code=exc.code,
        )
    state = store.get_status(engine)
    unchanged = (
        state.source_version == release.version
        and state.package_integrity == release.integrity
        and state.active_generation_id is not None
    )
    return RefreshResult(
        status=state.status,
        source_version=release.version,
        records_promoted=0,
        skipped_unchanged=unchanged,
    )


def _completion_time(fixed_time: datetime | None) -> datetime:
    return _as_utc(fixed_time or datetime.now(UTC))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


__all__ = [
    "ReferenceStoreError",
    "RefreshResult",
    "SnapshotClient",
    "preview_release",
    "refresh_index",
]
