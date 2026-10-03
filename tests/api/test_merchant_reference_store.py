"""Transactional behavior for isolated public merchant-reference generations."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine

from penge.api.merchant_reference import store
from penge.api.merchant_reference.service import refresh_index
from penge.api.merchant_reference.store_models import (
    MerchantReferenceGeneration,
    ReferenceBase,
)
from penge.ingest.merchant_reference.nsi import (
    NsiRelease,
    NsiSnapshot,
    NsiSourceError,
    PublicMerchantReference,
)

_VERSION_1 = "8.0.20260918"
_VERSION_2 = "8.0.20260919"
_TARBALL_BASE = "https://registry.npmjs.org/name-suggestion-index/-/name-suggestion-index-"
_CATALOG_BASE = "https://cdn.jsdelivr.net/npm/name-suggestion-index@"


@pytest.fixture
def engine() -> Iterator[Engine]:
    test_engine = create_engine("sqlite+pysqlite:///:memory:")
    ReferenceBase.metadata.create_all(test_engine)
    try:
        yield test_engine
    finally:
        test_engine.dispose()


def _release(version: str) -> NsiRelease:
    return NsiRelease(
        version=version,
        license="BSD-3-Clause",
        integrity="sha512-YWJj",
        tarball_url=f"{_TARBALL_BASE}{version}.tgz",
    )


def _snapshot(version: str, *, names: tuple[str, ...] = ("Acme", "Acme")) -> NsiSnapshot:
    retrieved = datetime(2026, 9, 20, tzinfo=UTC)
    revision = datetime(2026, 9, 18, tzinfo=UTC)
    references = tuple(
        PublicMerchantReference(
            source_entity_id=f"synthetic-{version}-{index}",
            label=name,
            aliases=(name, f"{name} {index}"),
            category_path="brands/shop/supermarket",
            wikidata_id=None,
            source_version=version,
            source_revision_at=revision,
            source_url=f"{_CATALOG_BASE}{version}/dist/json/nsi.json",
        )
        for index, name in enumerate(names)
    )
    return NsiSnapshot(
        source_version=version,
        source_generated_at=revision,
        retrieved_at=retrieved,
        source_url=f"{_CATALOG_BASE}{version}/dist/json/nsi.json",
        sha256=hashlib.sha256(version.encode()).hexdigest(),
        record_count=len(references),
        records=references,
    )


class _PublicClient:
    def __init__(self, version: str, snapshot: NsiSnapshot) -> None:
        self.version = version
        self.snapshot = snapshot
        self.fetch_count = 0

    def discover_release(self) -> NsiRelease:
        return _release(self.version)

    def fetch_snapshot(self, release: NsiRelease | None = None) -> NsiSnapshot:
        assert release == _release(self.version)
        self.fetch_count += 1
        return self.snapshot


class _FailingClient:
    def discover_release(self) -> NsiRelease:
        raise NsiSourceError("source_timeout", "Public package request timed out.")

    def fetch_snapshot(self, release: NsiRelease | None = None) -> NsiSnapshot:
        raise AssertionError(f"must not fetch snapshot for {release}")


class _ObservingClient(_PublicClient):
    def __init__(
        self,
        engine: Engine,
        version: str,
        snapshot: NsiSnapshot,
    ) -> None:
        super().__init__(version, snapshot)
        self.engine = engine
        self.status_during_download: store.ReferenceIndexState | None = None
        self.active_match_during_download: store.ReferenceSearch | None = None

    def fetch_snapshot(self, release: NsiRelease | None = None) -> NsiSnapshot:
        self.status_during_download = store.get_status(self.engine)
        self.active_match_during_download = store.search(self.engine, "Old merchant")
        return super().fetch_snapshot(release)


def test_promotion_is_searchable_and_name_collisions_are_ambiguous(engine: Engine) -> None:
    snapshot = _snapshot(_VERSION_1)
    store.promote_snapshot(engine, snapshot, _release(_VERSION_1))

    state = store.get_status(engine)
    result = store.search(engine, "ACME")

    assert state.status == "current"
    assert state.source_version == _VERSION_1
    assert state.record_count == 2
    assert state.license == "BSD-3-Clause"
    assert result.match_status == "ambiguous"
    assert result.source_status == "current"
    assert len(result.matches) == 2
    assert result.truncated is False


def test_reference_tables_are_isolated_from_household_identity_contracts() -> None:
    assert set(ReferenceBase.metadata.tables) == {
        "merchant_reference_generation",
        "merchant_reference",
        "merchant_reference_alias",
        "merchant_reference_refresh_state",
    }


def test_failed_refresh_keeps_active_generation_and_next_run_can_retry(engine: Engine) -> None:
    first_snapshot = _snapshot(_VERSION_1, names=("Acme old",))
    store.promote_snapshot(engine, first_snapshot, _release(_VERSION_1))

    failure = refresh_index(engine, _FailingClient())

    assert failure.status == "stale"
    assert failure.error_code == "source_timeout"
    stale_state = store.get_status(engine)
    assert stale_state.status == "stale"
    assert stale_state.source_version == _VERSION_1
    assert stale_state.error_code == "source_timeout"
    assert store.search(engine, "Acme old").matches[0].source_version == _VERSION_1

    client = _PublicClient(_VERSION_2, _snapshot(_VERSION_2, names=("Acme new",)))
    retried = refresh_index(engine, client)

    assert retried.ok
    assert retried.source_version == _VERSION_2
    assert retried.records_promoted == 1
    assert client.fetch_count == 1
    assert store.get_status(engine).status == "current"
    assert store.get_status(engine).source_version == _VERSION_2
    assert store.search(engine, "Acme new").matches[0].source_version == _VERSION_2
    assert store.search(engine, "Acme old").matches == ()


def test_previous_generation_remains_active_until_complete_promotion(engine: Engine) -> None:
    first_snapshot = _snapshot(_VERSION_1, names=("Old merchant",))
    store.promote_snapshot(engine, first_snapshot, _release(_VERSION_1))
    old_generation_id = store.get_status(engine).active_generation_id
    client = _ObservingClient(
        engine,
        _VERSION_2,
        _snapshot(_VERSION_2, names=("New merchant",)),
    )

    result = refresh_index(engine, client)

    assert result.ok
    assert client.status_during_download is not None
    assert client.status_during_download.status == "refreshing"
    assert client.status_during_download.source_version == _VERSION_1
    assert client.status_during_download.candidate_version == _VERSION_2
    assert client.status_during_download.active_generation_id == old_generation_id
    assert client.active_match_during_download is not None
    assert client.active_match_during_download.source_status == "refreshing"
    assert client.active_match_during_download.matches[0].label == "Old merchant"
    assert store.get_status(engine).source_version == _VERSION_2


def test_abandoned_refresh_becomes_stale_without_hiding_active_generation(engine: Engine) -> None:
    snapshot = _snapshot(_VERSION_1, names=("Acme",))
    store.promote_snapshot(engine, snapshot, _release(_VERSION_1))
    last_attempt = datetime(2026, 9, 20, 0, tzinfo=UTC)
    store.mark_refresh_started(engine, now=last_attempt)
    now = datetime(2026, 9, 20, 3, tzinfo=UTC)

    status = store.get_status(engine, now=now)
    search = store.search(engine, "Acme")

    assert status.status == "stale"
    assert status.source_version == _VERSION_1
    assert search.source_status == "stale"
    assert search.matches[0].label == "Acme"


def test_first_refresh_failure_reports_failed_without_an_active_generation(
    engine: Engine,
) -> None:
    result = refresh_index(engine, _FailingClient())

    status = store.get_status(engine)
    search = store.search(engine, "Acme")

    assert result.status == "failed"
    assert result.error_code == "source_timeout"
    assert status.status == "failed"
    assert status.active_generation_id is None
    assert status.source_version is None
    assert search.match_status == "no_match"
    assert search.source_status == "failed"


def test_unchanged_release_skips_full_snapshot_fetch(engine: Engine) -> None:
    snapshot = _snapshot(_VERSION_1, names=("Acme",))
    store.promote_snapshot(engine, snapshot, _release(_VERSION_1))
    client = _PublicClient(_VERSION_1, snapshot)

    result = refresh_index(engine, client)

    assert result.ok
    assert result.skipped_unchanged
    assert result.records_promoted == 0
    assert client.fetch_count == 0


def test_search_marks_result_set_truncated_at_requested_limit(engine: Engine) -> None:
    snapshot = _snapshot(
        _VERSION_1,
        names=("Acme", "Acme", "Acme"),
    )
    store.promote_snapshot(engine, snapshot, _release(_VERSION_1))

    result = store.search(engine, "Acme", limit=2)

    assert result.match_status == "ambiguous"
    assert len(result.matches) == 2
    assert result.truncated


def test_promotion_retains_only_current_and_previous_generation(engine: Engine) -> None:
    for version, label in (
        (_VERSION_1, "Acme 1"),
        (_VERSION_2, "Acme 2"),
        ("8.0.20260920", "Acme 3"),
    ):
        snapshot = _snapshot(version, names=(label,))
        store.promote_snapshot(engine, snapshot, _release(version))

    with engine.connect() as connection:
        generation_count = connection.scalar(
            select(func.count()).select_from(MerchantReferenceGeneration)
        )
        retained_versions: set[str] = set(
            connection.scalars(select(MerchantReferenceGeneration.source_version))
        )

    assert generation_count == 2
    assert store.search(engine, "Acme 3").matches[0].source_version == "8.0.20260920"
    assert retained_versions == {_VERSION_2, "8.0.20260920"}
    assert store.search(engine, "Acme 1").matches == ()


def test_invalid_search_query_is_rejected(engine: Engine) -> None:
    with pytest.raises(ValueError, match="at least one letter or number"):
        store.search(engine, "!!!")
