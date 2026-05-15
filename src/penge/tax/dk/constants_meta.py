"""Metadata registry for DK (and DE) annual planning constants.

Every statutory tax rate, threshold, and cap that Penge embeds in source
code must be reviewed each year when SKAT / Ankestyrelsen publish their
*satser*. This module records, for each constant:

- which Python symbol holds the live value;
- the calendar year in which the value was last confirmed against an
  official source;
- a stable URL that resolves to the authoritative annual figures;
- a short description of what the constant represents.

Usage
-----

Check for potentially stale constants before running a projection::

    from penge.tax.dk.constants_meta import check_freshness
    stale = check_freshness(current_year=2026)
    for meta in stale:
        print(f"WARNING: {meta.name!r} source year is {meta.source_year}")

Integrate with the projection audit record::

    from penge.sim.registry import build_standard_audit_record
    # build_standard_audit_record() uses source_year from this module automatically.

See ``docs/tax/dk-refresh-checklist.md`` for the full annual refresh
procedure and checklist.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "ALL_PLANNING_CONSTANTS",
    "ConstantMeta",
    "check_freshness",
]


@dataclass(frozen=True)
class ConstantMeta:
    """Metadata for a single planning constant.

    Args:
        name: Human-readable constant name (used in audit records and docs).
        constant: Python attribute name, e.g. ``"ASK_RATE"``.
        module: Dotted module path where the constant is defined,
            e.g. ``"penge.tax.aktiesparekonto"``.
        publisher: Authority that publishes this value, e.g. ``"SKAT"``,
            ``"Ankestyrelsen"``, ``"Folkepensionsloven"``.  Used in audit
            record source strings (``"{publisher} {source_year}"``).
        source_year: The calendar year for which the value was confirmed
            from an official source.  Update this each time the constant
            is refreshed.
        source_url: Canonical URL of the official source publication.
        unit: Dimension of the value, e.g. ``"%"`` or ``"DKK"``.
        notes: Optional short annotation — context, caveats, estimation notes.
    """

    name: str
    constant: str
    module: str
    publisher: str
    source_year: int
    source_url: str
    unit: str
    notes: str = ""


# ---------------------------------------------------------------------------
# Denmark — ASK (Aktiesparekonto)
# ---------------------------------------------------------------------------

_ASK_RATE = ConstantMeta(
    name="DK ASK tax rate",
    constant="ASK_RATE",
    module="penge.tax.aktiesparekonto",
    publisher="SKAT",
    source_year=2026,
    source_url="https://skat.dk/borger/aktier-og-investeringsbeviser/aktiesparekonto",
    unit="%",
    notes="Flat annual mark-to-market rate on ASK gains (17 %). Stable since 2019.",
)

_ASK_DEPOSIT_CAPS = ConstantMeta(
    name="DK ASK cumulative deposit cap",
    constant="ASK_DEPOSIT_CAPS",
    module="penge.tax.aktiesparekonto",
    publisher="SKAT",
    source_year=2025,
    source_url="https://skat.dk/data/satser",
    unit="DKK",
    notes=(
        "Lifetime net-deposit ceiling, indexed annually by SKAT. "
        "Add new year entry each November/December. "
        "2026 value is estimated — replace with SKAT-confirmed figure."
    ),
)

# ---------------------------------------------------------------------------
# Denmark — PAL-skat
# ---------------------------------------------------------------------------

_PAL_RATE = ConstantMeta(
    name="DK PAL-skat rate",
    constant="PAL_RATE",
    module="penge.tax.pal",
    publisher="SKAT",
    source_year=2026,
    source_url="https://skat.dk/borger/pension/pensionsafkastskat",
    unit="%",
    notes="15.3 % annual tax on pension-pot returns; stable since the 1990s.",
)

# ---------------------------------------------------------------------------
# Denmark — Aktieindkomst (lagerbeskatning)
# ---------------------------------------------------------------------------

_AKTIEINDKOMST_LOW_RATE = ConstantMeta(
    name="DK Aktieindkomst low rate",
    constant="AKTIEINDKOMST_LOW_RATE",
    module="penge.sim.liquid",
    publisher="SKAT",
    source_year=2026,
    source_url="https://skat.dk/data/satser/skattesatser-2026",
    unit="%",
    notes="27 % on gains up to annual threshold; stable since 2012.",
)

_AKTIEINDKOMST_HIGH_RATE = ConstantMeta(
    name="DK Aktieindkomst high rate",
    constant="AKTIEINDKOMST_HIGH_RATE",
    module="penge.sim.liquid",
    publisher="SKAT",
    source_year=2026,
    source_url="https://skat.dk/data/satser/skattesatser-2026",
    unit="%",
    notes="42 % on gains above annual threshold; stable since 2012.",
)

_AKTIEINDKOMST_THRESHOLDS = ConstantMeta(
    name="DK Aktieindkomst threshold per person",
    constant="AKTIEINDKOMST_THRESHOLDS",
    module="penge.sim.liquid",
    publisher="SKAT",
    source_year=2025,
    source_url="https://skat.dk/data/satser",
    unit="DKK",
    notes=(
        "Annual per-person threshold; gains above are taxed at 42 %. "
        "Indexed by wage index. 2026 value is estimated — confirm from SKAT."
    ),
)

# ---------------------------------------------------------------------------
# Denmark — Topskat
# ---------------------------------------------------------------------------

_TOPSKAT_RATE = ConstantMeta(
    name="DK Topskat rate",
    constant="DK_TOPSKAT_RATE",
    module="penge.tax.dk.rates",
    publisher="SKAT",
    source_year=2026,
    source_url="https://skat.dk/data/satser/skattesatser-2026",
    unit="%",
    notes="15 % surtax on personal income above the annual threshold.",
)

_TOPSKAT_THRESHOLD = ConstantMeta(
    name="DK Topskat threshold",
    constant="DK_TOPSKAT_THRESHOLD_DKK",
    module="penge.tax.dk.rates",
    publisher="SKAT",
    source_year=2026,
    source_url="https://skat.dk/data/satser/skattesatser-2026",
    unit="DKK",
    notes="Annual personal-income threshold above which Topskat is levied.",
)

# ---------------------------------------------------------------------------
# Denmark — Folkepension
# ---------------------------------------------------------------------------

_FOLKEPENSION_GRUNDBELOEB = ConstantMeta(
    name="DK Folkepension grundbeløb (monthly)",
    constant="FOLKEPENSION_GRUNDBELOEB_MONTHLY_DKK",
    module="penge.tax.dk.rates",
    publisher="Ankestyrelsen",
    source_year=2026,
    source_url="https://www.ankestyrelsen.dk/satser/satser-for-folkepension",
    unit="DKK/month",
    notes="Universal state pension base amount; not means-tested.",
)

_FOLKEPENSION_TILLAEG_SINGLE = ConstantMeta(
    name="DK Folkepension tillæg — single (monthly maximum)",
    constant="FOLKEPENSION_TILLAEG_SINGLE_MONTHLY_DKK",
    module="penge.tax.dk.rates",
    publisher="Ankestyrelsen",
    source_year=2026,
    source_url="https://www.ankestyrelsen.dk/satser/satser-for-folkepension",
    unit="DKK/month",
    notes="Maximum means-tested supplement for single pensioner.",
)

_FOLKEPENSION_TILLAEG_MARRIED = ConstantMeta(
    name="DK Folkepension tillæg — married (monthly maximum)",
    constant="FOLKEPENSION_TILLAEG_MARRIED_MONTHLY_DKK",
    module="penge.tax.dk.rates",
    publisher="Ankestyrelsen",
    source_year=2026,
    source_url="https://www.ankestyrelsen.dk/satser/satser-for-folkepension",
    unit="DKK/month",
    notes="Maximum means-tested supplement for married/cohabiting pensioner.",
)

_FOLKEPENSION_MODREGNING_RATE = ConstantMeta(
    name="DK Folkepension modregning rate",
    constant="FOLKEPENSION_MODREGNING_RATE",
    module="penge.tax.dk.rates",
    publisher="Ankestyrelsen",
    source_year=2026,
    source_url="https://www.ankestyrelsen.dk/satser/satser-for-folkepension",
    unit="%",
    notes="Tillæg is reduced by this fraction of private pension income > threshold.",
)

_FOLKEPENSION_INCOME_THRESHOLD = ConstantMeta(
    name="DK Folkepension income threshold",
    constant="FOLKEPENSION_INCOME_THRESHOLD_DKK",
    module="penge.tax.dk.rates",
    publisher="Ankestyrelsen",
    source_year=2026,
    source_url="https://www.ankestyrelsen.dk/satser/satser-for-folkepension",
    unit="DKK/year",
    notes="Annual private-income threshold; no modregning below this amount.",
)

_FOLKEPENSION_AGE_SCHEDULE = ConstantMeta(
    name="DK Folkepensionsalder schedule",
    constant="FOLKEPENSION_AGE_SCHEDULE",
    module="penge.tax.dk.rates",
    publisher="Folkepensionsloven",
    source_year=2026,
    source_url=(
        "https://www.borger.dk/pension-og-efterloen/folkepension"
        "/Artikler/Hvornaar-kan-du-faa-folkepension"
    ),
    unit="age (years)",
    notes=(
        "Calendar-year indexed retirement age. 67 until 2030, 68 until 2035, "
        "69 from 2035 (subject to life-expectancy revision; review every 5 years)."
    ),
)

# ---------------------------------------------------------------------------
# Master list
# ---------------------------------------------------------------------------

ALL_PLANNING_CONSTANTS: tuple[ConstantMeta, ...] = (
    _ASK_RATE,
    _ASK_DEPOSIT_CAPS,
    _PAL_RATE,
    _AKTIEINDKOMST_LOW_RATE,
    _AKTIEINDKOMST_HIGH_RATE,
    _AKTIEINDKOMST_THRESHOLDS,
    _TOPSKAT_RATE,
    _TOPSKAT_THRESHOLD,
    _FOLKEPENSION_GRUNDBELOEB,
    _FOLKEPENSION_TILLAEG_SINGLE,
    _FOLKEPENSION_TILLAEG_MARRIED,
    _FOLKEPENSION_MODREGNING_RATE,
    _FOLKEPENSION_INCOME_THRESHOLD,
    _FOLKEPENSION_AGE_SCHEDULE,
)
"""All planning constants registered for annual review.

Each entry carries a :attr:`~ConstantMeta.source_year` that records
when the value was last confirmed against an official source.  Use
:func:`check_freshness` to detect constants that may need updating.
"""


def check_freshness(current_year: int, *, max_age: int = 1) -> list[ConstantMeta]:
    """Return constants whose source year is more than *max_age* years old.

    A constant with ``source_year == current_year - 1`` is acceptable (the
    previous year's SKAT satser are the most recent available for a new
    calendar year). Constants with ``source_year <= current_year - max_age - 1``
    are flagged as potentially stale.

    Args:
        current_year: The year to check against (typically the current
            calendar year).  Must be a positive integer (>= 1).
        max_age: Maximum acceptable age of a constant's source in years.
            Defaults to ``1`` (i.e. a constant confirmed in ``current_year - 1``
            is still considered fresh).  Must be >= 0.

    Returns:
        List of :class:`ConstantMeta` entries with stale source years,
        ordered as in :data:`ALL_PLANNING_CONSTANTS`.  An empty list means
        all constants are fresh.

    Raises:
        ValueError: If *current_year* is not a positive integer or *max_age*
            is negative.
        TypeError: If either argument is not an integer.
    """
    if not isinstance(current_year, int) or isinstance(current_year, bool):  # reject bool
        raise TypeError(f"current_year must be an int, got {type(current_year).__name__!r}")
    if not isinstance(max_age, int) or isinstance(max_age, bool):  # reject bool
        raise TypeError(f"max_age must be an int, got {type(max_age).__name__!r}")
    if current_year < 1:
        raise ValueError(f"current_year must be >= 1, got {current_year!r}")
    if max_age < 0:
        raise ValueError(f"max_age must be >= 0, got {max_age!r}")

    cutoff = current_year - max_age - 1
    return [m for m in ALL_PLANNING_CONSTANTS if m.source_year <= cutoff]
