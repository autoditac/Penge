"""Pydantic v2 frozen models for parsed ABIS list records."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", strict=False)


class AbisRecord(_Frozen):
    """One ISIN row from a Skat ABIS CSV.

    ``registered_years`` is the set of years the fund is on the list
    (lagerbeskatning applies). ``unregistered_years`` is the set of
    years explicitly marked as not-on-list. The two are disjoint.

    ``country``, ``shareclass``, ``lei``, ``cvr``, ``subfund``,
    ``tin``, ``name`` may be ``None`` when Skat writes ``[tom]``.
    """

    isin: str
    country: str | None
    shareclass: str | None
    lei: str | None
    cvr: str | None
    subfund: str | None
    tin: str | None
    name: str | None
    registered_years: frozenset[int]
    unregistered_years: frozenset[int]


class ListingObservation(_Frozen):
    """One ``(ISIN, tax_year, listed)`` observation derived from a CSV.

    Multiple observations per ISIN are produced (one per year). The
    loader writes one ``instrument_dk_abis_listing`` row per
    observation matched to a known instrument.
    """

    isin: str
    tax_year: int
    listed: bool
