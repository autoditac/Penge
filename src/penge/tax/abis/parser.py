"""Pure CSV parser for Skat's ABIS list.

The CSV is downloaded from skat.dk and ships in UTF-8 with these
quirks (verified empirically against the 2020-2025 file):

- The header row is bilingual and contains a leading BOM.
- Empty cells are written as ``[tom]`` (Danish for "empty"), not as
  the empty string.
- ``ISIN-kode`` may carry trailing whitespace.
- Year-set columns are usually ``,``-separated (and quoted) but are
  occasionally ``.``-separated; both must be accepted.
- About 0.7 % of ISINs appear in two rows (one per share-class). The
  parser does **not** dedupe — the loader merges by ISIN.

Pure, no I/O outside of the explicit ``parse_abis_csv(path)`` entry
point.
"""

from __future__ import annotations

import csv
import logging
import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Final

from penge.tax.abis.constants import (
    ABIS_PLACEHOLDER,
    COL_COUNTRY,
    COL_CVR,
    COL_ISIN,
    COL_LEI,
    COL_NAME,
    COL_REG_YEARS,
    COL_SHARECLASS,
    COL_SUBFUND,
    COL_TIN,
    COL_UNREG_YEARS,
    EXPECTED_HEADERS,
    ISIN_LENGTH,
)
from penge.tax.abis.models import AbisRecord

log = logging.getLogger("penge.tax.abis.parser")

# Years are 4 digits. Skat occasionally uses ``.`` as separator
# (``2024.2025``) instead of ``,``; we accept both.
_YEAR_SEP_RE: Final = re.compile(r"[,.]")
_ISIN_RE: Final = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")


def parse_abis_csv(path: str | Path) -> tuple[AbisRecord, ...]:
    """Parse the given Skat ABIS CSV and return one record per row.

    Rows whose ISIN column does not contain a valid 12-char ISIN are
    skipped with a structured warning. Header row is validated: a
    deviation aborts parsing rather than silently misaligning.
    """
    p = Path(path)
    with p.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return ()
        _validate_header(header)
        return tuple(_records_from_rows(reader))


def _records_from_rows(rows: Iterable[list[str]]) -> Iterator[AbisRecord]:
    for row in rows:
        if not row or all(not c.strip() for c in row):
            continue
        if len(row) < len(EXPECTED_HEADERS):
            log.warning(
                "ABIS row has %d cells, expected %d; skipped: %r",
                len(row),
                len(EXPECTED_HEADERS),
                row,
            )
            continue
        isin_raw = row[COL_ISIN].strip()
        if not _looks_like_isin(isin_raw):
            log.warning("ABIS row skipped: invalid ISIN %r", isin_raw)
            continue
        yield AbisRecord(
            isin=isin_raw,
            country=_clean(row[COL_COUNTRY]),
            shareclass=_clean(row[COL_SHARECLASS]),
            lei=_clean(row[COL_LEI]),
            cvr=_clean(row[COL_CVR]),
            subfund=_clean(row[COL_SUBFUND]),
            tin=_clean(row[COL_TIN]),
            name=_clean(row[COL_NAME]),
            registered_years=parse_year_set(row[COL_REG_YEARS]),
            unregistered_years=parse_year_set(row[COL_UNREG_YEARS]),
        )


def parse_year_set(raw: str | None) -> frozenset[int]:
    """Parse ``"2024,2025"`` / ``"2024.2025"`` / ``""`` / ``"[tom]"``.

    Returns an empty frozenset for missing / placeholder values.
    Non-numeric tokens are dropped with a warning.
    """
    if raw is None:
        return frozenset()
    s = raw.strip()
    if not s or s == ABIS_PLACEHOLDER:
        return frozenset()
    out: set[int] = set()
    for tok in _YEAR_SEP_RE.split(s):
        t = tok.strip()
        if not t:
            continue
        try:
            out.add(int(t))
        except ValueError:
            log.warning("ABIS year token %r is not an integer; dropped", t)
    return frozenset(out)


def _validate_header(header: list[str]) -> None:
    # Strip BOM from the first cell if csv didn't already (we use
    # utf-8-sig, so this is defensive).
    if header and header[0].startswith("\ufeff"):
        header = [header[0].lstrip("\ufeff"), *header[1:]]
    if len(header) < len(EXPECTED_HEADERS):
        raise ValueError(
            f"ABIS CSV header has {len(header)} columns, expected at least "
            f"{len(EXPECTED_HEADERS)}: {header!r}"
        )
    for i, expected in enumerate(EXPECTED_HEADERS):
        if header[i].strip() != expected:
            raise ValueError(
                f"ABIS CSV header column {i} is {header[i]!r}, expected "
                f"{expected!r}. Refusing to parse misaligned data."
            )


def _looks_like_isin(s: str) -> bool:
    return len(s) == ISIN_LENGTH and bool(_ISIN_RE.match(s))


def _clean(s: str | None) -> str | None:
    if s is None:
        return None
    t = s.strip()
    if not t or t == ABIS_PLACEHOLDER:
        return None
    return t
