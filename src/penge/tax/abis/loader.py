"""ABIS list → Postgres loader.

Idempotent. Re-running with the same CSV converges to the same
state. See ADR-0009 for the precedence + interpretation rules.

Key invariants:

- ``instrument.dk_tax_treatment_source = 'manual'`` is sticky;
  the loader never overwrites such rows.
- One ``instrument_dk_abis_listing`` row per ``(instrument_id,
  tax_year)`` is upserted per import.
- The current effective treatment is derived from the most recent
  imported tax year per instrument:
    listed=true → ``lagerbeskatning``;
    listed=false → ``NULL`` (forces user review).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import MetaData, Table, and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from penge.tax.abis.constants import (
    DK_TAX_LAGERBESKATNING,
    SOURCE_ABIS,
    SOURCE_MANUAL,
    TREATMENT_VALUES,
)
from penge.tax.abis.models import AbisRecord, ListingObservation
from penge.tax.abis.parser import parse_abis_csv

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine

log = logging.getLogger("penge.tax.abis.loader")


@dataclass(frozen=True, slots=True)
class LoadResult:
    """Counts of writes performed by one ``load_*`` call."""

    csv_rows: int
    matched_isins: int
    unmatched_isins: int
    listing_observations: int
    instruments_classified: int
    instruments_cleared: int


# --------------------------------------------------------------------------- #
# Public entrypoints
# --------------------------------------------------------------------------- #


def load_abis_csv(
    engine: Engine,
    *,
    csv_path: str | Path,
) -> LoadResult:
    """Parse a Skat ABIS CSV and reconcile it against ``instrument``."""
    records = parse_abis_csv(csv_path)
    return load_abis_records(
        engine,
        records=records,
        source_file=str(Path(csv_path).name),
    )


def load_abis_records(
    engine: Engine,
    *,
    records: Sequence[AbisRecord],
    source_file: str | None,
) -> LoadResult:
    """Same as :func:`load_abis_csv` but takes pre-parsed records."""
    if not records:
        return LoadResult(0, 0, 0, 0, 0, 0)

    observations = tuple(_records_to_observations(records))

    meta = MetaData()
    tables = _reflect(engine, meta)
    isins = sorted({r.isin for r in records})

    with engine.begin() as conn:
        instrument_ids_by_isin = _resolve_instrument_ids(conn, tables["instrument"], isins=isins)
        n_obs = _upsert_listings(
            conn,
            tables["instrument_dk_abis_listing"],
            observations=observations,
            instrument_ids_by_isin=instrument_ids_by_isin,
            source_file=source_file,
        )
        classified, cleared = _refresh_treatments(
            conn,
            tables["instrument"],
            tables["instrument_dk_abis_listing"],
            instrument_ids=tuple(instrument_ids_by_isin.values()),
        )

    matched = len(instrument_ids_by_isin)
    unmatched = len(isins) - matched
    if unmatched:
        log.info("ABIS load: %d ISINs not in instrument table; skipped", unmatched)

    return LoadResult(
        csv_rows=len(records),
        matched_isins=matched,
        unmatched_isins=unmatched,
        listing_observations=n_obs,
        instruments_classified=classified,
        instruments_cleared=cleared,
    )


def apply_manual_override(
    engine: Engine,
    *,
    isin: str,
    treatment: str,
) -> bool:
    """Force ``dk_tax_treatment`` for the instrument matching ``isin``.

    Sets ``dk_tax_treatment_source='manual'`` so subsequent ABIS
    imports do not overwrite the value. Returns ``True`` when a row
    was updated, ``False`` when no instrument matched the ISIN.
    """
    if treatment not in TREATMENT_VALUES:
        raise ValueError(f"treatment must be one of {TREATMENT_VALUES!r}, got {treatment!r}")
    meta = MetaData()
    instrument = Table("instrument", meta, autoload_with=engine)
    with engine.begin() as conn:
        result = conn.execute(
            instrument.update()
            .where(instrument.c.isin == isin)
            .values(
                dk_tax_treatment=treatment,
                dk_tax_treatment_source=SOURCE_MANUAL,
                updated_at=func.now(),
            )
        )
        return bool(result.rowcount)


def clear_manual_override(
    engine: Engine,
    *,
    isin: str,
) -> bool:
    """Drop a manual override.

    The next ABIS import will re-derive the treatment from the latest
    listing observation.
    """
    meta = MetaData()
    instrument = Table("instrument", meta, autoload_with=engine)
    with engine.begin() as conn:
        result = conn.execute(
            instrument.update()
            .where(
                instrument.c.isin == isin,
                instrument.c.dk_tax_treatment_source == SOURCE_MANUAL,
            )
            .values(
                dk_tax_treatment=None,
                dk_tax_treatment_source=None,
                updated_at=func.now(),
            )
        )
        return bool(result.rowcount)


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _records_to_observations(records: Sequence[AbisRecord]) -> list[ListingObservation]:
    """Flatten ``AbisRecord``s into one observation per (ISIN, year).

    When the same ISIN appears across multiple share-class rows, all
    listed/not-listed years are unioned. If a year shows up as both
    listed and not-listed (Skat occasionally has internal disagreement
    across share-classes), ``listed=True`` wins — being on the list
    even via one share-class is enough for the tax engine.
    """
    by_isin: dict[str, tuple[set[int], set[int]]] = {}
    for r in records:
        listed, unlisted = by_isin.setdefault(r.isin, (set(), set()))
        listed.update(r.registered_years)
        unlisted.update(r.unregistered_years)

    observations: list[ListingObservation] = []
    for isin, (listed, unlisted) in by_isin.items():
        # ``listed`` wins on conflict.
        unlisted_only = unlisted - listed
        for y in sorted(listed):
            observations.append(ListingObservation(isin=isin, tax_year=y, listed=True))
        for y in sorted(unlisted_only):
            observations.append(ListingObservation(isin=isin, tax_year=y, listed=False))
    return observations


def _reflect(engine: Engine, meta: MetaData) -> dict[str, Table]:
    return {
        name: Table(name, meta, autoload_with=engine)
        for name in ("instrument", "instrument_dk_abis_listing")
    }


def _resolve_instrument_ids(
    conn: Connection,
    instrument: Table,
    *,
    isins: Sequence[str],
) -> dict[str, str]:
    if not isins:
        return {}
    rows = conn.execute(
        select(instrument.c.id, instrument.c.isin).where(instrument.c.isin.in_(isins))
    ).all()
    return {str(isin): str(iid) for iid, isin in rows}


def _upsert_listings(
    conn: Connection,
    listing: Table,
    *,
    observations: Sequence[ListingObservation],
    instrument_ids_by_isin: dict[str, str],
    source_file: str | None,
) -> int:
    n = 0
    for obs in observations:
        instrument_id = instrument_ids_by_isin.get(obs.isin)
        if instrument_id is None:
            continue
        stmt = pg_insert(listing).values(
            instrument_id=instrument_id,
            tax_year=obs.tax_year,
            listed=obs.listed,
            source_file=source_file,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="ux_instrument_dk_abis_listing__instrument_id_tax_year",
            set_={
                "listed": stmt.excluded.listed,
                "source_file": stmt.excluded.source_file,
                "imported_at": func.now(),
            },
        )
        conn.execute(stmt)
        n += 1
    return n


def _refresh_treatments(
    conn: Connection,
    instrument: Table,
    listing: Table,
    *,
    instrument_ids: Sequence[str],
) -> tuple[int, int]:
    """Re-derive ``instrument.dk_tax_treatment`` from the latest listing.

    Returns ``(classified, cleared)`` — how many rows were set to
    ``lagerbeskatning`` vs cleared to ``NULL`` by this call. Rows
    with ``dk_tax_treatment_source = 'manual'`` are left alone.
    """
    if not instrument_ids:
        return 0, 0
    classified = 0
    cleared = 0
    # Pull the latest tax_year listing per instrument.
    latest_subq = (
        select(
            listing.c.instrument_id,
            func.max(listing.c.tax_year).label("max_year"),
        )
        .where(listing.c.instrument_id.in_(instrument_ids))
        .group_by(listing.c.instrument_id)
        .subquery()
    )
    rows = conn.execute(
        select(
            listing.c.instrument_id,
            listing.c.tax_year,
            listing.c.listed,
        ).join(
            latest_subq,
            and_(
                listing.c.instrument_id == latest_subq.c.instrument_id,
                listing.c.tax_year == latest_subq.c.max_year,
            ),
        )
    ).all()

    for instrument_id, _year, listed in rows:
        if listed:
            new_treatment: str | None = DK_TAX_LAGERBESKATNING
            new_source: str | None = SOURCE_ABIS
        else:
            new_treatment = None
            new_source = None
        result = conn.execute(
            instrument.update()
            .where(
                instrument.c.id == instrument_id,
                # Sticky manual overrides — never touch them.
                (
                    (instrument.c.dk_tax_treatment_source.is_(None))
                    | (instrument.c.dk_tax_treatment_source == SOURCE_ABIS)
                ),
            )
            .values(
                dk_tax_treatment=new_treatment,
                dk_tax_treatment_source=new_source,
                updated_at=func.now(),
            )
        )
        if result.rowcount:
            if listed:
                classified += 1
            else:
                cleared += 1
    return classified, cleared


__all__ = [
    "LoadResult",
    "apply_manual_override",
    "clear_manual_override",
    "load_abis_csv",
    "load_abis_records",
]
