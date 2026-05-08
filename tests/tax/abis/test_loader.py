"""Loader integration tests for the ABIS list ingestor.

Gated on ``PENGE_TEST_DATABASE_URL``. Runs the migrations forward,
seeds a couple of ``instrument`` rows, runs the loader, and asserts
the operational + audit tables converge to the expected state.
"""

from __future__ import annotations

import codecs
import os
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

DB_URL = os.environ.get("PENGE_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    DB_URL is None,
    reason="PENGE_TEST_DATABASE_URL is not set; loader tests need a live Postgres.",
)


@pytest.fixture  # type: ignore[untyped-decorator]
def engine(tmp_path: Path) -> Iterator[Engine]:
    """Apply migrations, hand back an engine, drop schema afterwards.

    Each test runs in its own schema so they cannot collide.
    """
    assert DB_URL is not None
    schema = f"abis_test_{uuid.uuid4().hex[:12]}"
    eng = create_engine(DB_URL)
    with eng.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    # Run alembic against this schema.
    test_url = f"{DB_URL}?options=-csearch_path%3D{schema}"
    test_eng = create_engine(test_url)
    _alembic_upgrade(test_url)
    try:
        yield test_eng
    finally:
        test_eng.dispose()
        with eng.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        eng.dispose()


def _alembic_upgrade(database_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


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
    # Most recent year (2025) is "not registered" → NULL/NULL.
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
