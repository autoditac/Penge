"""Typed data model for the monthly report.

The renderers (:mod:`penge.ops.report.markdown`,
:mod:`penge.ops.report.pdf`) accept a fully-populated
:class:`ReportData` and never touch the database directly. The
loader in :mod:`penge.ops.report.data` is responsible for producing
this object; tests can build one in-process with synthetic figures.

All currency amounts are :class:`~decimal.Decimal` so we never round
through float on the path to the rendered report. Two-decimal-place
display formatting happens in the renderers.

Every section type carries an ``available`` flag. The loader sets it
to ``False`` (and populates ``note``) when the underlying mart /
calculator is not present on the current main branch. The renderer
then prints a "TODO" placeholder instead of fake numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class HeaderSection:
    """Static metadata at the top of the report."""

    month: str
    """ISO month string, ``YYYY-MM``."""

    generated_at: datetime
    """UTC timestamp of generation."""

    schema_versions: dict[str, str]
    """Map of component → version string (e.g. ``"alembic": "abc123"``)."""

    git_sha: str
    """Short SHA of the commit the generator ran from, or ``"unknown"``."""


@dataclass(frozen=True)
class NetWorthSection:
    """End-of-month net-worth snapshot + 12-month sparkline."""

    available: bool
    eom_eur: Decimal | None = None
    eom_dkk: Decimal | None = None
    mom_delta_eur: Decimal | None = None
    yoy_delta_eur: Decimal | None = None
    # Ordered (month_iso, total_eur) pairs, most-recent last. Up to 12.
    sparkline_eur: list[tuple[str, Decimal]] = field(default_factory=list)
    note: str = ""


@dataclass(frozen=True)
class CashflowSection:
    """Month inflow / outflow / net and the top categories."""

    available: bool
    inflow_eur: Decimal | None = None
    outflow_eur: Decimal | None = None
    net_eur: Decimal | None = None
    # Ordered list of (category_label, signed_amount_eur). Up to 5.
    top_categories: list[tuple[str, Decimal]] = field(default_factory=list)
    note: str = ""


@dataclass(frozen=True)
class AllocationSection:
    """Asset allocation by class and by jurisdiction."""

    available: bool
    # Each entry: (label, eur_value, fraction_of_total).
    by_class: list[tuple[str, Decimal, Decimal]] = field(default_factory=list)
    by_jurisdiction: list[tuple[str, Decimal, Decimal]] = field(default_factory=list)
    note: str = ""


@dataclass(frozen=True)
class TaxSection:
    """YTD DK + DE tax estimates from the Phase-3 calculators."""

    available: bool
    dk_estimate_dkk: Decimal | None = None
    dk_components: list[tuple[str, Decimal]] = field(default_factory=list)
    de_estimate_eur: Decimal | None = None
    de_components: list[tuple[str, Decimal]] = field(default_factory=list)
    note: str = ""


@dataclass(frozen=True)
class FireSection:
    """Monte-Carlo snapshot: portfolio percentiles + median FIRE year."""

    available: bool
    horizon_year: int | None = None
    p10_eur: Decimal | None = None
    p50_eur: Decimal | None = None
    p90_eur: Decimal | None = None
    p_goal_met: Decimal | None = None
    median_fire_year: int | None = None
    note: str = ""


@dataclass(frozen=True)
class OpsSection:
    """Vault inbox stats, backup status, ingestion errors."""

    available: bool
    vault_classified: int | None = None
    vault_unsorted: int | None = None
    last_backup_at: date | None = None
    last_backup_age_days: int | None = None
    sentry_errors_last_month: int | None = None
    note: str = ""


@dataclass(frozen=True)
class ReportData:
    """Aggregate report payload consumed by the renderers."""

    header: HeaderSection
    net_worth: NetWorthSection
    cashflow: CashflowSection
    allocation: AllocationSection
    tax: TaxSection
    fire: FireSection
    ops: OpsSection
