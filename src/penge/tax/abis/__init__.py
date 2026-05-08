"""Skat ABIS list ingestion.

Parses the official "ABIS-listen" CSV (Skat's catalogue of
Danish-recognised aktiebaserede investeringsselskaber) and writes
DK tax-treatment classifications onto the operational
``instrument`` table plus the per-year audit table
``instrument_dk_abis_listing``.

See ADR-0009 and ``docs/connectors/abis.md`` for the rules.
"""

from __future__ import annotations

from penge.tax.abis.constants import (
    ABIS_PLACEHOLDER,
    DK_TAX_LAGERBESKATNING,
    DK_TAX_REALISATION,
    SOURCE_ABIS,
    SOURCE_MANUAL,
    TREATMENT_VALUES,
)
from penge.tax.abis.loader import (
    LoadResult,
    apply_manual_override,
    clear_manual_override,
    load_abis_csv,
    load_abis_records,
)
from penge.tax.abis.models import AbisRecord, ListingObservation
from penge.tax.abis.parser import parse_abis_csv, parse_year_set

__all__ = [
    "ABIS_PLACEHOLDER",
    "DK_TAX_LAGERBESKATNING",
    "DK_TAX_REALISATION",
    "SOURCE_ABIS",
    "SOURCE_MANUAL",
    "TREATMENT_VALUES",
    "AbisRecord",
    "ListingObservation",
    "LoadResult",
    "apply_manual_override",
    "clear_manual_override",
    "load_abis_csv",
    "load_abis_records",
    "parse_abis_csv",
    "parse_year_set",
]
