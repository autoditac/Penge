"""Route handlers for the read API.

Thin layer: validate query parameters (FastAPI/Pydantic), call the
typed data-access functions in :mod:`penge.api.data`, shape the rows
into the response models from :mod:`penge.api.models`, and apply
server-side masking. No SQL and no business logic lives here.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query

from penge.api import data
from penge.api.models import (
    AccountSummary,
    AllocationDimension,
    AllocationResponse,
    AllocationSlice,
    CashflowPoint,
    CashflowSeriesResponse,
    FreshnessResponse,
    GroupBy,
    MartFreshness,
    NetWorthPoint,
    NetWorthSeriesResponse,
    NetWorthTotalPoint,
    NetWorthTotalSeriesResponse,
)
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
    """Account dimension with IBAN and name suffix masked server-side."""
    return [
        AccountSummary(
            account_id=str(row["account_id"]),
            entity_id=str(row["entity_id"]),
            entity_name=str(row["entity_name"]),
            provider=str(row["provider"]),
            name=mask_account_name(str(row["name"])),
            kind=str(row["kind"]),
            currency=str(row["currency"]),
            iban_masked=mask_iban(row["iban"] if isinstance(row["iban"], str) else None),
        )
        for row in data.fetch_accounts()
    ]


@router.get("/meta/freshness", response_model=FreshnessResponse)
def meta_freshness() -> FreshnessResponse:
    """Latest data date and row count per mart, for staleness banners."""
    return FreshnessResponse(
        marts=[MartFreshness.model_validate(row) for row in data.fetch_freshness()]
    )
