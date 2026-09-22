"""Route handlers for the read API.

Thin layer: validate query parameters (FastAPI/Pydantic), call the
typed data-access functions in :mod:`penge.api.data`, shape the rows
into the response models from :mod:`penge.api.models`, and apply
server-side masking. No SQL and no business logic lives here.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.engine import Engine

from penge.analytics import ReturnPoint, ReturnsError, mwr_from_series, twr_summary
from penge.api import data
from penge.api.connections.config import ConnectionsConfig
from penge.api.imports.engine import get_import_engine
from penge.api.models import (
    AccountSummary,
    AllocationDimension,
    AllocationResponse,
    AllocationSlice,
    BenchmarkInfo,
    BenchmarkPoint,
    BenchmarkSeriesResponse,
    CashflowPoint,
    CashflowSeriesResponse,
    CurrencyReturnSummary,
    FeesResponse,
    FeeYearRow,
    FreshnessResponse,
    GroupBy,
    MartFreshness,
    MetaRefreshResponse,
    NetWorthPoint,
    NetWorthSeriesResponse,
    NetWorthTotalPoint,
    NetWorthTotalSeriesResponse,
    ReturnsPoint,
    ReturnsScope,
    ReturnsSeriesResponse,
    ReturnsSummaryEntry,
    ReturnsSummaryResponse,
)
from penge.api.refresh_config import MetaRefreshConfig
from penge.ops.net_worth_refresh import (
    DbtRefreshError,
    DbtRunner,
    LockUnavailableError,
    RefreshRunner,
    RefreshStateError,
    exclusive_lock,
    mark_refresh_pending,
)
from penge.web.config import database_url
from penge.web.mask import mask_account_name, mask_iban

log = logging.getLogger("penge.api")

router = APIRouter()

# One year of daily data is the default window; clients page through
# larger ranges explicitly. The cap bounds worst-case payloads
# (instructions: every many-row read is paginated).
DEFAULT_WINDOW_DAYS = 365
DEFAULT_LIMIT = 1_000
MAX_LIMIT = 10_000

_SinceParam = Annotated[
    date | None,
    Query(description="First day of the window (inclusive). Default: one year ago."),
]
_UntilParam = Annotated[
    date | None,
    Query(description="Last day of the window (inclusive). Default: today."),
]
_AccountParam = Annotated[str | None, Query(description="Filter to one account id.")]
_EntityParam = Annotated[str | None, Query(description="Filter to one entity id.")]
_LimitParam = Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Page size.")]
_OffsetParam = Annotated[int, Query(ge=0, description="Page start offset.")]


def _window(since: date | None, until: date | None) -> tuple[date, date]:
    """Apply the default one-year window to missing bounds."""
    resolved_until = until or date.today()
    resolved_since = since or resolved_until - timedelta(days=DEFAULT_WINDOW_DAYS)
    return resolved_since, resolved_until


@router.get("/net-worth/daily", response_model=NetWorthSeriesResponse | NetWorthTotalSeriesResponse)
def net_worth_daily(
    since: _SinceParam = None,
    until: _UntilParam = None,
    account_id: _AccountParam = None,
    entity_id: _EntityParam = None,
    group: GroupBy = GroupBy.ACCOUNT,
    limit: _LimitParam = DEFAULT_LIMIT,
    offset: _OffsetParam = 0,
) -> NetWorthSeriesResponse | NetWorthTotalSeriesResponse:
    """Daily net-worth series, per account or summed per day."""
    resolved_since, resolved_until = _window(since, until)
    if group is GroupBy.TOTAL:
        total_rows, count = data.fetch_net_worth_total(
            since=resolved_since,
            until=resolved_until,
            account_id=account_id,
            entity_id=entity_id,
            limit=limit,
            offset=offset,
        )
        return NetWorthTotalSeriesResponse(
            points=[NetWorthTotalPoint.model_validate(row) for row in total_rows],
            limit=limit,
            offset=offset,
            total=count,
        )
    rows, count = data.fetch_net_worth(
        since=resolved_since,
        until=resolved_until,
        account_id=account_id,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
    )
    return NetWorthSeriesResponse(
        points=[NetWorthPoint.model_validate(row) for row in rows],
        limit=limit,
        offset=offset,
        total=count,
    )


@router.get("/cashflow/daily", response_model=CashflowSeriesResponse)
def cashflow_daily(
    since: _SinceParam = None,
    until: _UntilParam = None,
    account_id: _AccountParam = None,
    entity_id: _EntityParam = None,
    limit: _LimitParam = DEFAULT_LIMIT,
    offset: _OffsetParam = 0,
) -> CashflowSeriesResponse:
    """Daily cashflow series per account (absent days mean zero)."""
    resolved_since, resolved_until = _window(since, until)
    rows, count = data.fetch_cashflow(
        since=resolved_since,
        until=resolved_until,
        account_id=account_id,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
    )
    return CashflowSeriesResponse(
        points=[CashflowPoint.model_validate(row) for row in rows],
        limit=limit,
        offset=offset,
        total=count,
    )


_DIMENSION_COLUMN = {
    AllocationDimension.ENTITY: "entity_name",
    AllocationDimension.CURRENCY: "account_currency",
    AllocationDimension.KIND: "account_kind",
}


@router.get("/allocation/current", response_model=AllocationResponse)
def allocation_current(by: AllocationDimension = AllocationDimension.KIND) -> AllocationResponse:
    """Latest-day allocation grouped by entity, currency, or account kind."""
    rows = data.fetch_allocation_rows()
    if not rows:
        return AllocationResponse(as_of=None, by=by, slices=[])

    column = _DIMENSION_COLUMN[by]
    first_as_of = rows[0]["as_of"]
    as_of = first_as_of if isinstance(first_as_of, date) else None

    eur_by_label: dict[str, Decimal] = {}
    dkk_by_label: dict[str, Decimal] = {}
    for row in rows:
        label = str(row[column])
        eur = row["balance_eur"]
        dkk = row["balance_dkk"]
        if isinstance(eur, Decimal):
            eur_by_label[label] = eur_by_label.get(label, Decimal(0)) + eur
        if isinstance(dkk, Decimal):
            dkk_by_label[label] = dkk_by_label.get(label, Decimal(0)) + dkk

    eur_total = sum(eur_by_label.values(), Decimal(0))
    slices = [
        AllocationSlice(
            label=label,
            balance_eur=eur_by_label.get(label),
            balance_dkk=dkk_by_label.get(label),
            weight_eur=(eur_by_label[label] / eur_total)
            if label in eur_by_label and eur_total
            else None,
        )
        for label in sorted(set(eur_by_label) | set(dkk_by_label))
    ]
    return AllocationResponse(as_of=as_of, by=by, slices=slices)


@router.get("/accounts", response_model=list[AccountSummary])
def accounts() -> list[AccountSummary]:
    """Account dimension with masked identifiers and per-account import freshness."""
    return [
        AccountSummary(
            account_id=str(row["account_id"]),
            entity_id=str(row["entity_id"]),
            entity_name=str(row["entity_name"]),
            provider=str(row["provider"]),
            name=mask_account_name(row["name"] if isinstance(row["name"], str) else None),
            kind=str(row["kind"]),
            currency=str(row["currency"]),
            iban_masked=mask_iban(row["iban"] if isinstance(row["iban"], str) else None),
            last_updated_at=row["last_updated_at"]
            if isinstance(row["last_updated_at"], datetime)
            else None,
        )
        for row in data.fetch_accounts()
    ]


@router.get("/meta/freshness", response_model=FreshnessResponse)
def meta_freshness() -> FreshnessResponse:
    """Latest data date and row count per mart, for staleness banners."""
    return FreshnessResponse(
        marts=[MartFreshness.model_validate(row) for row in data.fetch_freshness()]
    )


# ---------------------------------------------------------------------------
# WebUI-triggered dbt-only refresh (issue #285, ADR-0046)
# ---------------------------------------------------------------------------


def get_refresh_engine() -> Engine:
    """Return the write-enabled engine dbt schema promotion runs through."""
    return get_import_engine()


def get_refresh_state_dir() -> Path:
    """Resolve the shared refresh-state directory (lock + pending marker).

    Reuses :class:`ConnectionsConfig` so the WebUI refresh route, the
    manual connection-sync route, and the scheduled worker all resolve
    ``PENGE_REFRESH_STATE_DIR`` from one place.
    """
    return ConnectionsConfig.from_env().refresh_state_dir


def get_dbt_runner(
    engine: Annotated[Engine, Depends(get_refresh_engine)],
) -> RefreshRunner:
    """Build the same :class:`DbtRunner` the scheduled worker uses."""
    config = MetaRefreshConfig.from_env()
    try:
        return DbtRunner(
            engine,
            project_dir=config.dbt_project_dir,
            profiles_dir=config.dbt_profiles_dir,
            database_url=database_url(),
        )
    except DbtRefreshError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.post(
    "/meta/refresh",
    response_model=MetaRefreshResponse,
    responses={
        status.HTTP_502_BAD_GATEWAY: {
            "description": (
                "The shadow dbt build, tests, or schema promotion failed. "
                "Live marts and the pending marker are unchanged."
            ),
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": (
                "The refresh lock is already held by the scheduled worker, a "
                "connection sync, or another manual trigger; retry shortly."
            ),
        },
    },
)
def meta_refresh(
    dbt_runner: Annotated[RefreshRunner, Depends(get_dbt_runner)],
    refresh_state_dir: Annotated[Path, Depends(get_refresh_state_dir)],
) -> MetaRefreshResponse:
    """Trigger the guarded dbt-only refresh, without re-syncing connections.

    Reuses the exact shadow-build/test-plus-atomic-promotion path
    (``DbtRunner.refresh``) and the shared advisory lock + durable
    pending marker described in ADR-0046, so this route, the manual
    connection-sync route, and the scheduled worker can never overlap.
    The pending marker is created *before* ``refresh()`` runs (mirroring
    the scheduled worker's own write-intent tracking) so that, if this
    process is killed or dbt fails, the next scheduled run still sees
    a pending refresh and retries automatically; it is cleared only
    once promotion succeeds.
    """
    lock_file = refresh_state_dir / "refresh.lock"
    pending_refresh_file = refresh_state_dir / "pending"
    try:
        with exclusive_lock(lock_file):
            try:
                mark_refresh_pending(pending_refresh_file)
            except OSError as exc:
                raise RefreshStateError(
                    f"could not persist pending refresh marker: {type(exc).__name__}"
                ) from exc
            dbt_runner.refresh()
            try:
                pending_refresh_file.unlink(missing_ok=True)
            except OSError as exc:
                # The dbt build/promotion already succeeded; a leftover
                # marker only costs the next scheduled run a redundant
                # (idempotent) rebuild, so this is logged, not raised.
                log.error(
                    "meta_refresh_pending_marker_clear_failed path=%s code=%s",
                    pending_refresh_file,
                    type(exc).__name__,
                )
    except (LockUnavailableError, RefreshStateError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except DbtRefreshError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        # `DbtRunner.refresh()` also drops/promotes shadow schemas with raw
        # SQLAlchemy calls and shells out to dbt directly, so a database
        # error or a missing dbt executable can escape `DbtRefreshError`.
        # Treat any such failure the same way the scheduled worker does:
        # a sanitized 502, live marts and the pending marker untouched.
        log.error("meta_refresh_unexpected_failure code=%s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="unexpected dbt refresh failure",
        ) from exc
    return MetaRefreshResponse(status="succeeded", completed_at=datetime.now(UTC))


# ---------------------------------------------------------------------------
# Returns, benchmarks, and fees (dashboard v2, issue #206)
# ---------------------------------------------------------------------------

_ScopeKeyParam = Annotated[
    str | None,
    Query(description="Filter to one scope key (account id, asset-class key, or 'household')."),
]


@router.get("/returns/daily", response_model=ReturnsSeriesResponse)
def returns_daily(
    scope: ReturnsScope = ReturnsScope.HOUSEHOLD,
    scope_key: _ScopeKeyParam = None,
    since: _SinceParam = None,
    until: _UntilParam = None,
    limit: _LimitParam = DEFAULT_LIMIT,
    offset: _OffsetParam = 0,
) -> ReturnsSeriesResponse:
    """Daily return factors per scope from ``mart_returns_daily``."""
    resolved_since, resolved_until = _window(since, until)
    rows, count = data.fetch_returns(
        since=resolved_since,
        until=resolved_until,
        scope=scope.value,
        scope_key=scope_key,
        limit=limit,
        offset=offset,
    )
    return ReturnsSeriesResponse(
        points=[ReturnsPoint.model_validate(row) for row in rows],
        limit=limit,
        offset=offset,
        total=count,
    )


def _summary_error(message: str) -> CurrencyReturnSummary:
    """A summary leg that explains itself instead of carrying numbers."""
    return CurrencyReturnSummary(
        cumulative_return=None, annualized_return=None, mwr_annualized=None, error=message
    )


def _currency_summary(rows: list[dict[str, object]], suffix: str) -> CurrencyReturnSummary:
    """Chain-link one currency leg of one scope key's window rows."""
    points: list[ReturnPoint] = []
    missing = 0
    for row in rows:
        begin = row[f"begin_mv_{suffix}"]
        end = row[f"end_mv_{suffix}"]
        flow = row[f"net_flow_{suffix}"]
        as_of = row["as_of"]
        if not isinstance(begin, Decimal) or not isinstance(end, Decimal):
            missing += 1
            continue
        if not isinstance(as_of, date):  # pragma: no cover - driver always returns date
            missing += 1
            continue
        points.append(
            ReturnPoint(
                as_of=as_of,
                begin_value=begin,
                end_value=end,
                net_flow=flow if isinstance(flow, Decimal) else Decimal(0),
            )
        )
    if missing:
        return _summary_error(f"{missing} day(s) lack {suffix.upper()} conversion")
    if not points:
        return _summary_error("no data in window")
    try:
        summary = twr_summary(points)
    except ReturnsError as exc:
        return _summary_error(str(exc))
    return CurrencyReturnSummary(
        cumulative_return=summary.cumulative_return,
        annualized_return=summary.annualized_return,
        mwr_annualized=mwr_from_series(points),
        error=None,
    )


@router.get("/returns/summary", response_model=ReturnsSummaryResponse)
def returns_summary(
    scope: ReturnsScope = ReturnsScope.HOUSEHOLD,
    since: _SinceParam = None,
    until: _UntilParam = None,
) -> ReturnsSummaryResponse:
    """Chain-linked TWR and MWR per scope key over the window.

    Computation runs server-side through ``penge.analytics.returns``
    so the UI and any other client see identical figures. A scope key
    whose series cannot be chain-linked faithfully reports an ``error``
    note instead of a number.
    """
    resolved_since, resolved_until = _window(since, until)
    rows = data.fetch_returns_window(since=resolved_since, until=resolved_until, scope=scope.value)
    by_key: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_key.setdefault(str(row["scope_key"]), []).append(row)

    entries: list[ReturnsSummaryEntry] = []
    for key, key_rows in sorted(by_key.items()):
        dates = [row["as_of"] for row in key_rows if isinstance(row["as_of"], date)]
        entries.append(
            ReturnsSummaryEntry(
                scope=scope,
                scope_key=key,
                start_date=min(dates) if dates else None,
                end_date=max(dates) if dates else None,
                days=len(key_rows),
                eur=_currency_summary(key_rows, "eur"),
                dkk=_currency_summary(key_rows, "dkk"),
            )
        )
    return ReturnsSummaryResponse(
        since=resolved_since, until=resolved_until, scope=scope, entries=entries
    )


@router.get("/benchmarks", response_model=list[BenchmarkInfo])
def benchmarks() -> list[BenchmarkInfo]:
    """Instruments with ingested price history, usable as benchmarks."""
    return [BenchmarkInfo.model_validate(row) for row in data.fetch_benchmarks()]


_InstrumentParam = Annotated[str, Query(description="Instrument id from /benchmarks.")]


@router.get("/benchmarks/daily", response_model=BenchmarkSeriesResponse)
def benchmarks_daily(
    instrument_id: _InstrumentParam,
    since: _SinceParam = None,
    until: _UntilParam = None,
    limit: _LimitParam = DEFAULT_LIMIT,
    offset: _OffsetParam = 0,
) -> BenchmarkSeriesResponse:
    """Daily close series of one benchmark, in its native currency.

    An unknown instrument id yields an empty series, not an error —
    the UI treats it the same as "no prices in window".
    """
    resolved_since, resolved_until = _window(since, until)
    rows, count = data.fetch_benchmark_series(
        instrument_id=instrument_id,
        since=resolved_since,
        until=resolved_until,
        limit=limit,
        offset=offset,
    )
    return BenchmarkSeriesResponse(
        instrument_id=instrument_id,
        points=[BenchmarkPoint.model_validate(row) for row in rows],
        limit=limit,
        offset=offset,
        total=count,
    )


@router.get("/returns/fees", response_model=FeesResponse)
def returns_fees(
    since: _SinceParam = None,
    until: _UntilParam = None,
) -> FeesResponse:
    """Yearly fee totals per account, for the fee-drag view."""
    resolved_since, resolved_until = _window(since, until)
    rows = data.fetch_fees(since=resolved_since, until=resolved_until)
    return FeesResponse(
        since=resolved_since,
        until=resolved_until,
        rows=[FeeYearRow.model_validate(row) for row in rows],
    )
