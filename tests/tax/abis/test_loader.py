"""Loader integration tests for the ABIS list ingestor.

Gated on ``PENGE_TEST_DATABASE_URL`` (or ``DATABASE_URL``). The
fixture pattern follows ``tests/ingest/nordnet/test_loader.py``:
``alembic upgrade head`` runs once per session, then each test
truncates the relevant tables before running.
"""

from __future__ import annotations

import codecs
import os
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import MetaData, Table, create_engine, select, text
from sqlalchemy.engine import Engine

from penge.tax.abis import (
    DK_TAX_LAGERBESKATNING,
    SOURCE_ABIS,
    SOURCE_MANUAL,
    apply_manual_override,
    clear_manual_override,
    load_abis_csv,
)
from tests.tax.abis.fixtures import ABIS_CSV_FIXTURE_TEXT

_DB_URL = os.environ.get("PENGE_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    _DB_URL is None,
    reason="set PENGE_TEST_DATABASE_URL or DATABASE_URL to run loader tests",
)

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")  # type: ignore[untyped-decorator]
def engine() -> Iterator[Engine]:
    """Engine pointed at the test DB; runs ``alembic upgrade head`` once."""
    assert _DB_URL is not None
    eng = create_engine(_DB_URL)
    env = {**os.environ, "DATABASE_URL": _DB_URL}
    subprocess.run(  # noqa: S603
        ["alembic", "upgrade", "head"],  # noqa: S607
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture(autouse=True)  # type: ignore[untyped-decorator]
def _truncate(engine: Engine) -> Iterator[None]:
    """Wipe ABIS-touching tables before each test."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE instrument_dk_abis_listing, holding_snapshot, "
                "transaction, instrument, account, entity "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield


@pytest.fixture  # type: ignore[untyped-decorator]
def fixture_csv(tmp_path: Path) -> Path:
    p = tmp_path / "abis.csv"
    p.write_bytes(codecs.BOM_UTF8 + ABIS_CSV_FIXTURE_TEXT.encode("utf-8"))
    return p


def _seed_instrument(engine: Engine, *, isin: str, name: str) -> uuid.UUID:
    meta = MetaData()
    instrument = Table("instrument", meta, autoload_with=engine)
    new_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            instrument.insert().values(
                id=new_id,
                isin=isin,
                name=name,
                kind="equity_fund",
                currency="EUR",
            )
        )
    return new_id


def _treatment(engine: Engine, isin: str) -> tuple[str | None, str | None]:
    meta = MetaData()
    instrument = Table("instrument", meta, autoload_with=engine)
    with engine.connect() as conn:
        row = conn.execute(
            select(
                instrument.c.dk_tax_treatment,
                instrument.c.dk_tax_treatment_source,
            ).where(instrument.c.isin == isin)
        ).one()
    return row[0], row[1]


def test_load_abis_csv_classifies_listed_isins_as_lagerbeskatning(
    engine: Engine, fixture_csv: Path
) -> None:
    _seed_instrument(engine, isin="XX0000000001", name="Synthetic A")
    result = load_abis_csv(engine, csv_path=fixture_csv)
    assert result.matched_isins == 1
    assert result.unmatched_isins >= 2
    assert _treatment(engine, "XX0000000001") == (
        DK_TAX_LAGERBESKATNING,
        SOURCE_ABIS,
    )


def test_load_abis_csv_clears_treatment_for_delisted_isin(
    engine: Engine, fixture_csv: Path
) -> None:
    _seed_instrument(engine, isin="XX0000000004", name="Delisted")
    load_abis_csv(engine, csv_path=fixture_csv)
    # Most recent year (2025) is "not registered" -> NULL/NULL.
    assert _treatment(engine, "XX0000000004") == (None, None)


def test_load_abis_csv_is_idempotent(engine: Engine, fixture_csv: Path) -> None:
    _seed_instrument(engine, isin="XX0000000001", name="Synthetic A")
    first = load_abis_csv(engine, csv_path=fixture_csv)
    second = load_abis_csv(engine, csv_path=fixture_csv)
    assert first.listing_observations == second.listing_observations
    assert _treatment(engine, "XX0000000001") == (
        DK_TAX_LAGERBESKATNING,
        SOURCE_ABIS,
    )


def test_manual_override_is_sticky_across_re_imports(engine: Engine, fixture_csv: Path) -> None:
    _seed_instrument(engine, isin="XX0000000001", name="Synthetic A")
    load_abis_csv(engine, csv_path=fixture_csv)
    assert apply_manual_override(engine, isin="XX0000000001", treatment="realisation")
    assert _treatment(engine, "XX0000000001") == ("realisation", SOURCE_MANUAL)
    # Re-importing must not overwrite a manual decision.
    load_abis_csv(engine, csv_path=fixture_csv)
    assert _treatment(engine, "XX0000000001") == ("realisation", SOURCE_MANUAL)


def test_clear_manual_override_lets_next_import_re_derive(
    engine: Engine, fixture_csv: Path
) -> None:
    _seed_instrument(engine, isin="XX0000000001", name="Synthetic A")
    load_abis_csv(engine, csv_path=fixture_csv)
    apply_manual_override(engine, isin="XX0000000001", treatment="realisation")
    assert clear_manual_override(engine, isin="XX0000000001")
    assert _treatment(engine, "XX0000000001") == (None, None)
    load_abis_csv(engine, csv_path=fixture_csv)
    assert _treatment(engine, "XX0000000001") == (
        DK_TAX_LAGERBESKATNING,
        SOURCE_ABIS,
    )


def test_apply_manual_override_returns_false_for_unknown_isin(engine: Engine) -> None:
    assert not apply_manual_override(engine, isin="XX9999999999", treatment="realisation")


def test_apply_manual_override_rejects_unknown_treatment(engine: Engine) -> None:
    with pytest.raises(ValueError):
        apply_manual_override(engine, isin="XX0000000001", treatment="bogus")


def test_load_abis_csv_writes_listing_audit_rows(engine: Engine, fixture_csv: Path) -> None:
    iid = _seed_instrument(engine, isin="XX0000000001", name="Synthetic A")
    load_abis_csv(engine, csv_path=fixture_csv)
    meta = MetaData()
    listing = Table("instrument_dk_abis_listing", meta, autoload_with=engine)
    with engine.connect() as conn:
        rows = conn.execute(
            select(listing.c.tax_year, listing.c.listed).where(listing.c.instrument_id == iid)
        ).all()
    by_year = {y: listed for y, listed in rows}
    # Row 1 of the fixture: registered=2025, unregistered=2020-2024.
    assert by_year == {
        2020: False,
        2021: False,
        2022: False,
        2023: False,
        2024: False,
        2025: True,
    }
