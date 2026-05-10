"""Load the monthly report payload from the dbt marts.

The loader is intentionally fault-tolerant: every section is wrapped
in a try/except that, on failure or missing source, emits a section
with ``available=False`` and a short note. The renderers then print a
"TODO" placeholder so a partially-wired environment (e.g. a phase
where ``mart_cashflow_daily`` exists but the tax marts do not) still
produces a usable report.

The DB connection is created lazily so importing this module is
free of side effects.
"""

from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from .model import (
    AllocationSection,
    CashflowSection,
    FireSection,
    HeaderSection,
    NetWorthSection,
    OpsSection,
    ReportData,
    TaxSection,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

log = logging.getLogger("penge.ops.report.data")


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------


def _git_sha() -> str:
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no user input
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 - PATH lookup of git is fine
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    sha = result.stdout.strip()
    return sha or "unknown"


def _schema_versions(engine: Engine | None) -> dict[str, str]:
    versions: dict[str, str] = {}
    if engine is None:
        return versions
    try:
        from sqlalchemy import text

        with engine.connect() as conn:
            row = conn.execute(text("select version_num from alembic_version limit 1")).fetchone()
            if row is not None:
                versions["alembic"] = str(row[0])
    except Exception as exc:
        log.debug("schema_versions: %s", exc)
    return versions


def build_header(month: str, engine: Engine | None) -> HeaderSection:
    return HeaderSection(
        month=month,
        generated_at=datetime.now(UTC),
        schema_versions=_schema_versions(engine),
        git_sha=_git_sha(),
    )


# ---------------------------------------------------------------------------
# DB plumbing
# ---------------------------------------------------------------------------


def _database_url() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    # Fall back to assembled POSTGRES_* if available — same convention
    # as the ingest connectors.
    host = os.environ.get("POSTGRES_HOST")
    db = os.environ.get("POSTGRES_DB")
    user = os.environ.get("POSTGRES_USER")
    pw = os.environ.get("POSTGRES_PASSWORD")
    port = os.environ.get("POSTGRES_PORT", "5432")
    if host and db and user and pw:
        return f"postgresql+psycopg://{user}:{pw}@{host}:{port}/{db}"
    return None


def get_engine() -> Engine | None:
    """Return a lazy SQLAlchemy engine, or ``None`` if no URL is configured."""

    url = _database_url()
    if not url:
        return None
    try:
        from sqlalchemy import create_engine

        return create_engine(url, pool_pre_ping=True)
    except Exception as exc:
        log.warning("could not create engine: %s", exc)
        return None


_MONTHS_IN_YEAR = 12


def _eom_date(month: str) -> date:
    year, mon = (int(x) for x in month.split("-"))
    if mon == _MONTHS_IN_YEAR:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, mon + 1, 1) - timedelta(days=1)


def _bom_date(month: str) -> date:
    year, mon = (int(x) for x in month.split("-"))
    return date(year, mon, 1)


def _months_ago(month: str, n: int) -> str:
    year, mon = (int(x) for x in month.split("-"))
    idx = year * _MONTHS_IN_YEAR + (mon - 1) - n
    return f"{idx // _MONTHS_IN_YEAR:04d}-{idx % _MONTHS_IN_YEAR + 1:02d}"


# ---------------------------------------------------------------------------
# Section loaders — each returns a section with ``available=False`` on miss.
# ---------------------------------------------------------------------------


def load_net_worth(engine: Engine | None, month: str) -> NetWorthSection:
    if engine is None:
        return NetWorthSection(
            available=False,
            note="no DATABASE_URL configured; render skipped.",
        )
    try:
        from sqlalchemy import text

        eom = _eom_date(month)
        with engine.connect() as conn:
            row_now = conn.execute(
                text(
                    "select sum(balance_eur) as eur, sum(balance_dkk) as dkk "
                    "from analytics_marts.mart_net_worth_daily where as_of = :d"
                ),
                {"d": eom},
            ).fetchone()
            row_mom = conn.execute(
                text(
                    "select sum(balance_eur) from analytics_marts.mart_net_worth_daily "
                    "where as_of = :d"
                ),
                {"d": _eom_date(_months_ago(month, 1))},
            ).fetchone()
            row_yoy = conn.execute(
                text(
                    "select sum(balance_eur) from analytics_marts.mart_net_worth_daily "
                    "where as_of = :d"
                ),
                {"d": _eom_date(_months_ago(month, 12))},
            ).fetchone()
            sparkline_rows = conn.execute(
                text(
                    "select to_char(as_of, 'YYYY-MM') as m, sum(balance_eur) as eur "
                    "from analytics_marts.mart_net_worth_daily "
                    "where as_of <= :eom "
                    "and as_of >= :start "
                    "group by to_char(as_of, 'YYYY-MM') "
                    "order by m"
                ),
                {"eom": eom, "start": _bom_date(_months_ago(month, 11))},
            ).fetchall()
    except Exception as exc:
        return NetWorthSection(
            available=False, note=f"mart_net_worth_daily unavailable: {exc.__class__.__name__}"
        )

    if row_now is None or row_now[0] is None:
        return NetWorthSection(available=False, note="no data for end-of-month date.")

    eom_eur = Decimal(str(row_now[0]))
    eom_dkk = Decimal(str(row_now[1])) if row_now[1] is not None else None
    mom_prev = Decimal(str(row_mom[0])) if row_mom and row_mom[0] is not None else None
    yoy_prev = Decimal(str(row_yoy[0])) if row_yoy and row_yoy[0] is not None else None

    sparkline = [
        (str(r[0]), Decimal(str(r[1])))
        for r in sparkline_rows
        if r is not None and r[1] is not None
    ][-12:]

    return NetWorthSection(
        available=True,
        eom_eur=eom_eur,
        eom_dkk=eom_dkk,
        mom_delta_eur=(eom_eur - mom_prev) if mom_prev is not None else None,
        yoy_delta_eur=(eom_eur - yoy_prev) if yoy_prev is not None else None,
        sparkline_eur=sparkline,
    )


def load_cashflow(engine: Engine | None, month: str) -> CashflowSection:
    if engine is None:
        return CashflowSection(available=False, note="no DATABASE_URL configured; render skipped.")
    try:
        from sqlalchemy import text

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "select sum(inflow_eur) as inflow, sum(outflow_eur) as outflow, "
                    "sum(net_eur) as net "
                    "from analytics_marts.mart_cashflow_daily "
                    "where as_of >= :bom and as_of <= :eom"
                ),
                {"bom": _bom_date(month), "eom": _eom_date(month)},
            ).fetchone()
    except Exception as exc:
        return CashflowSection(
            available=False, note=f"mart_cashflow_daily unavailable: {exc.__class__.__name__}"
        )
    if row is None or row[0] is None:
        return CashflowSection(available=False, note="no cashflow rows for the month.")
    inflow = Decimal(str(row[0]))
    outflow = Decimal(str(row[1])) if row[1] is not None else Decimal("0")
    net = Decimal(str(row[2])) if row[2] is not None else inflow - outflow
    # A per-category mart does not yet exist on main (issue #46 v1 is
    # account-day grain only). Surface a placeholder rather than fake
    # numbers — this is the "render a placeholder with a TODO note"
    # contract from the issue scope.
    return CashflowSection(
        available=True,
        inflow_eur=inflow,
        outflow_eur=outflow,
        net_eur=net,
        top_categories=[],
        note="per-category breakdown pending; see #46 follow-up.",
    )


def load_allocation(engine: Engine | None, month: str) -> AllocationSection:
    # The asset-class / jurisdiction mart is a Phase-4 follow-up; no
    # source on main yet. Always degraded with a TODO marker.
    _ = (engine, month)
    return AllocationSection(
        available=False, note="asset-class / jurisdiction mart not yet on main."
    )


def load_tax(engine: Engine | None, month: str) -> TaxSection:
    _ = (engine, month)
    return TaxSection(
        available=False,
        note="Phase-3 tax YTD aggregation pending; see #36/#37/#38/#40.",
    )


def load_fire(engine: Engine | None, month: str) -> FireSection:
    _ = (engine, month)
    return FireSection(
        available=False,
        note="Monte-Carlo default config wiring pending; see penge.sim.montecarlo.",
    )


def load_ops(engine: Engine | None, month: str) -> OpsSection:
    _ = (engine, month)
    return OpsSection(
        available=False,
        note="vault / backup / Sentry aggregations pending.",
    )


def load_report_data(month: str, *, engine: Engine | None = None) -> ReportData:
    """Best-effort load of all sections.

    A missing engine, mart, or source yields a section with
    ``available=False`` rather than raising — so a fresh checkout with
    no database produces a complete (placeholder) report end-to-end.
    """

    eng = engine if engine is not None else get_engine()
    return ReportData(
        header=build_header(month, eng),
        net_worth=load_net_worth(eng, month),
        cashflow=load_cashflow(eng, month),
        allocation=load_allocation(eng, month),
        tax=load_tax(eng, month),
        fire=load_fire(eng, month),
        ops=load_ops(eng, month),
    )


# ---------------------------------------------------------------------------
# Public helpers exported for the renderer test paths.
# ---------------------------------------------------------------------------


def redact_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Convenience re-export of :func:`penge.ops.report.redact.redact_mapping`."""

    from .redact import redact_mapping

    return redact_mapping(row)
