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
from penge.analytics.household import BankTransaction, Category, previous_window
from penge.api import data
from penge.api.account_kinds import reporting_kind
from penge.api.connections.config import ConnectionsConfig
from penge.api.household_models import (
    HouseholdCategoryReportResponse,
    HouseholdGranularity,
    HouseholdReportFilters,
    HouseholdReportFreshness,
    HouseholdReportSummaryResponse,
    HouseholdReportTransactionsResponse,
)
from penge.api.household_reporting import (
    build_category_response,
    build_report_coverage,
    build_summary_response,
    build_transactions_response,
    categories_from_rows,
    category_descendant_ids,
    transactions_from_rows,
)
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
        if by is AllocationDimension.KIND:
            label = reporting_kind(label)
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
            reporting_kind=reporting_kind(str(row["kind"])),
            currency=str(row["currency"]),
            iban_masked=mask_iban(row["iban"] if isinstance(row["iban"], str) else None),
            last_updated_at=row["last_updated_at"]
            if isinstance(row["last_updated_at"], datetime)
            else None,
            balance_changed_on=row["balance_changed_on"]
            if isinstance(row["balance_changed_on"], date)
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
# Household reporting projection (issue #333, ADR-0052)
# ---------------------------------------------------------------------------

_HouseholdAccountParam = Annotated[
    list[str] | None,
    Query(description="Repeat to select checking-account ids; default is all checking accounts."),
]
_HouseholdEntityParam = Annotated[
    list[str] | None,
    Query(description="Repeat to filter household entity ids; default is all owned entities."),
]
_HouseholdCategoryParam = Annotated[
    str | None,
    Query(description="Category id; includes descendant categories."),
]


def _household_scope(
    *,
    since: date | None,
    until: date | None,
    account_ids: list[str] | None,
    entity_ids: list[str] | None,
) -> tuple[date, date, list[str], list[str]]:
    resolved_since, resolved_until = _window(since, until)
    if resolved_since > resolved_until:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="since must be on or before until",
        )
    resolved_entities = list(dict.fromkeys(entity_ids or []))
    if account_ids is None:
        resolved_accounts = data.fetch_household_default_accounts(entity_ids=resolved_entities)
    else:
        resolved_accounts = list(dict.fromkeys(account_ids))
        eligible_accounts = data.fetch_household_checking_accounts(
            account_ids=resolved_accounts,
            entity_ids=resolved_entities,
        )
        if set(eligible_accounts) != set(resolved_accounts):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="account_id must select checking accounts in the selected entity scope",
            )
    return resolved_since, resolved_until, resolved_accounts, resolved_entities


def _household_filters(
    *,
    since: date,
    until: date,
    account_ids: list[str],
    entity_ids: list[str],
    category_id: str | None,
    granularity: HouseholdGranularity,
) -> HouseholdReportFilters:
    return HouseholdReportFilters(
        since=since,
        until=until,
        account_ids=account_ids,
        entity_ids=entity_ids,
        category_id=category_id,
        granularity=granularity,
    )


def _household_freshness(
    *,
    account_ids: list[str],
    entity_ids: list[str],
    until: date,
) -> tuple[HouseholdReportFreshness, date | None]:
    row = data.fetch_household_report_freshness(
        account_ids=account_ids,
        entity_ids=entity_ids,
        until=until,
    )
    generated_at = datetime.now(UTC)
    history_start = row.get("history_start")
    latest_booking = row.get("latest_bank_booking_date")
    latest_import = row.get("latest_bank_import_at")
    latest_fx = row.get("latest_fx_rate_date")
    latest_detail = row.get("latest_payment_detail_sync_at")
    freshness = HouseholdReportFreshness(
        report_generated_at=generated_at,
        latest_bank_booking_date=latest_booking if isinstance(latest_booking, date) else None,
        latest_bank_import_at=latest_import if isinstance(latest_import, datetime) else None,
        latest_fx_rate_date=latest_fx if isinstance(latest_fx, date) else None,
        latest_payment_detail_sync_at=(
            latest_detail if isinstance(latest_detail, datetime) else None
        ),
    )
    return freshness, history_start if isinstance(history_start, date) else None


def _household_categories_and_transactions(
    *,
    since: date,
    until: date,
    account_ids: list[str],
    entity_ids: list[str],
) -> tuple[tuple[Category, ...], tuple[BankTransaction, ...]]:
    category_rows = data.fetch_household_categories()
    categories = categories_from_rows(category_rows)
    fact_rows = data.fetch_household_report_facts(
        since=since,
        until=until,
        account_ids=account_ids,
        entity_ids=entity_ids,
    )
    transactions = transactions_from_rows(fact_rows)
    return categories, transactions


def _household_category_transactions(
    *,
    rows: list[dict[str, object]],
) -> tuple[BankTransaction, ...]:
    transaction_ids = list(dict.fromkeys(str(row["transaction_id"]) for row in rows))
    details = data.fetch_household_payment_details(transaction_ids=transaction_ids)
    return transactions_from_rows(rows, details)


def _validate_household_category(
    categories: tuple[Category, ...],
    category_id: str | None,
) -> None:
    if category_id is None:
        return
    if category_id not in {category.category_id for category in categories}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="unknown category_id",
        )
    category_descendant_ids(categories, category_id)


@router.get(
    "/household/reports/summary",
    response_model=HouseholdReportSummaryResponse,
)
def household_report_summary(
    since: _SinceParam = None,
    until: _UntilParam = None,
    account_id: _HouseholdAccountParam = None,
    entity_id: _HouseholdEntityParam = None,
    category_id: _HouseholdCategoryParam = None,
    granularity: HouseholdGranularity = HouseholdGranularity.MONTH,
) -> HouseholdReportSummaryResponse:
    """Return household totals, comparison, trend, coverage, and freshness."""
    resolved_since, resolved_until, account_ids, entity_ids = _household_scope(
        since=since,
        until=until,
        account_ids=account_id,
        entity_ids=entity_id,
    )
    filters = _household_filters(
        since=resolved_since,
        until=resolved_until,
        account_ids=account_ids,
        entity_ids=entity_ids,
        category_id=category_id,
        granularity=granularity,
    )
    categories = categories_from_rows(data.fetch_household_categories())
    _validate_household_category(categories, category_id)
    previous_since, _ = previous_window(resolved_since, resolved_until)
    transactions = _household_category_transactions(
        rows=data.fetch_household_report_facts(
            since=previous_since,
            until=resolved_until,
            account_ids=account_ids,
            entity_ids=entity_ids,
        ),
    )
    freshness, history_start = _household_freshness(
        account_ids=account_ids,
        entity_ids=entity_ids,
        until=resolved_until,
    )
    coverage = build_report_coverage(
        transactions=transactions,
        categories=categories,
        since=resolved_since,
        until=resolved_until,
        account_ids=account_ids,
        entity_ids=entity_ids,
        category_id=category_id,
        history_start=history_start,
        unmatched_detail_count=data.fetch_household_unmatched_payment_detail_count(
            since=resolved_since,
            until=resolved_until,
            entity_ids=entity_ids,
        ),
    )
    return build_summary_response(
        transactions=transactions,
        categories=categories,
        filters=filters,
        coverage=coverage,
        freshness=freshness,
    )


@router.get(
    "/household/reports/categories",
    response_model=HouseholdCategoryReportResponse,
)
def household_report_categories(
    since: _SinceParam = None,
    until: _UntilParam = None,
    account_id: _HouseholdAccountParam = None,
    entity_id: _HouseholdEntityParam = None,
    category_id: _HouseholdCategoryParam = None,
    granularity: HouseholdGranularity = HouseholdGranularity.MONTH,
) -> HouseholdCategoryReportResponse:
    """Return descendant-inclusive category rollups and report coverage."""
    resolved_since, resolved_until, account_ids, entity_ids = _household_scope(
        since=since,
        until=until,
        account_ids=account_id,
        entity_ids=entity_id,
    )
    filters = _household_filters(
        since=resolved_since,
        until=resolved_until,
        account_ids=account_ids,
        entity_ids=entity_ids,
        category_id=category_id,
        granularity=granularity,
    )
    categories, transactions = _household_categories_and_transactions(
        since=resolved_since,
        until=resolved_until,
        account_ids=account_ids,
        entity_ids=entity_ids,
    )
    _validate_household_category(categories, category_id)
    freshness, history_start = _household_freshness(
        account_ids=account_ids,
        entity_ids=entity_ids,
        until=resolved_until,
    )
    coverage = build_report_coverage(
        transactions=transactions,
        categories=categories,
        since=resolved_since,
        until=resolved_until,
        account_ids=account_ids,
        entity_ids=entity_ids,
        category_id=category_id,
        history_start=history_start,
        unmatched_detail_count=data.fetch_household_unmatched_payment_detail_count(
            since=resolved_since,
            until=resolved_until,
            entity_ids=entity_ids,
        ),
    )
    return build_category_response(
        transactions=transactions,
        categories=categories,
        filters=filters,
        coverage=coverage,
        freshness=freshness,
    )


@router.get(
    "/household/reports/transactions",
    response_model=HouseholdReportTransactionsResponse,
)
def household_report_transactions(
    since: _SinceParam = None,
    until: _UntilParam = None,
    account_id: _HouseholdAccountParam = None,
    entity_id: _HouseholdEntityParam = None,
    category_id: _HouseholdCategoryParam = None,
    granularity: HouseholdGranularity = HouseholdGranularity.MONTH,
    search: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    limit: _LimitParam = DEFAULT_LIMIT,
    offset: _OffsetParam = 0,
) -> HouseholdReportTransactionsResponse:
    """Return a stable, paginated bank-grain transaction drilldown."""
    resolved_since, resolved_until, account_ids, entity_ids = _household_scope(
        since=since,
        until=until,
        account_ids=account_id,
        entity_ids=entity_id,
    )
    filters = _household_filters(
        since=resolved_since,
        until=resolved_until,
        account_ids=account_ids,
        entity_ids=entity_ids,
        category_id=category_id,
        granularity=granularity,
    )
    categories = categories_from_rows(data.fetch_household_categories())
    _validate_household_category(categories, category_id)
    selected_category_ids = (
        category_descendant_ids(categories, category_id) if category_id is not None else frozenset()
    )
    rows, total = data.fetch_household_transaction_page(
        since=resolved_since,
        until=resolved_until,
        account_ids=account_ids,
        entity_ids=entity_ids,
        category_ids=sorted(selected_category_ids),
        category_filter=category_id is not None,
        search=search,
        limit=limit,
        offset=offset,
    )
    transaction_ids = list(dict.fromkeys(str(row["transaction_id"]) for row in rows))
    details = data.fetch_household_payment_details(transaction_ids=transaction_ids)
    transactions = transactions_from_rows(rows, details)
    return build_transactions_response(
        transactions=transactions,
        categories=categories,
        filters=filters,
        search=search,
        limit=limit,
        offset=offset,
        total=total,
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
                "Live marts are unchanged; the pending marker is preserved "
                "(or created, if none existed yet) so the next scheduled "
                "run retries."
            ),
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": (
                "The refresh lock is already held by the scheduled worker, a "
                "connection sync, import commit, or another manual trigger, "
                "or durable refresh intent could not be persisted."
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
    connection-sync route, import commits, and the scheduled worker can
    never overlap.
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
    except LockUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="refresh lock is already held",
        ) from exc
    except RefreshStateError as exc:
        log.error("meta_refresh_state_unavailable code=%s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="refresh state is unavailable",
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
        # Post-promotion cleanup failures are handled as best-effort inside
        # `DbtRunner.refresh()` itself, so any exception reaching here means
        # promotion genuinely did not complete: live marts are unchanged, and
        # the pending marker (preserved, or created moments ago if none
        # existed) stays in place for the next scheduled run to retry.
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
