"""Typed read-only data access for the HTTP API.

All queries are parameterised SQLAlchemy ``text()`` against the dbt
marts in ``analytics_marts`` plus the canonical ``account`` /
``entity`` dimensions. Unlike the Streamlit layer this module returns
plain row mappings (no pandas): the API serialises straight from
``Decimal``-typed driver rows into Pydantic models, so amounts never
pass through binary floats.

The engine is created lazily and cached at module level so importing
this module never opens a network connection (mirrors
``penge.web.data``).
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy import text

# The API reuses the web layer's URL resolution (DATABASE_URL first,
# then POSTGRES_* parts) so both read-only frontends point at the same
# database by construction.
from penge.web.config import database_url

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date

    from sqlalchemy.engine import Engine


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine (lazily created)."""
    # Lazy so importing this module never requires the DB driver
    # (mirrors penge.web.data.get_engine).
    from sqlalchemy import create_engine  # Deliberately lazy; see above.

    return create_engine(
        database_url(),
        pool_pre_ping=True,
        # Read-only by design (ADR-0035): the psycopg dialect opens every
        # transaction READ ONLY, so accidental DML here fails loudly even
        # when the credentials would permit writes.
        execution_options={"postgresql_readonly": True},
    )


def _rows(sql: str, params: Mapping[str, object]) -> list[dict[str, object]]:
    """Run ``sql`` with bound ``params`` and return mapping rows."""
    with get_engine().connect() as conn:
        result = conn.execute(text(sql), dict(params))
        return [dict(row) for row in result.mappings()]


def _scalar(sql: str, params: Mapping[str, object]) -> object:
    """Run ``sql`` with bound ``params`` and return the first scalar."""
    with get_engine().connect() as conn:
        return conn.execute(text(sql), dict(params)).scalar()


def _count(sql: str, params: Mapping[str, object]) -> int:
    """Run a ``count(...)`` query and return the result as ``int``."""
    value = _scalar(sql, params)
    return value if isinstance(value, int) else 0


# ---------------------------------------------------------------------------
# Net worth
# ---------------------------------------------------------------------------

_SERIES_FILTER = """
    where as_of >= :since
      and as_of <= :until
      and (cast(:account_id as text) is null or account_id::text = :account_id)
      and (cast(:entity_id as text) is null or entity_id::text = :entity_id)
"""

_NET_WORTH_SQL = f"""
    select
        as_of,
        entity_id::text as entity_id,
        account_id::text as account_id,
        account_currency,
        balance_acct_ccy,
        balance_eur,
        balance_dkk
    from analytics_marts.mart_net_worth_daily
    {_SERIES_FILTER}
    order by as_of, account_id
    limit :limit offset :offset
"""

_NET_WORTH_COUNT_SQL = f"""
    select count(*)
    from analytics_marts.mart_net_worth_daily
    {_SERIES_FILTER}
"""

_NET_WORTH_TOTAL_SQL = f"""
    select
        as_of,
        sum(balance_eur) as balance_eur,
        sum(balance_dkk) as balance_dkk
    from analytics_marts.mart_net_worth_daily
    {_SERIES_FILTER}
    group by as_of
    order by as_of
    limit :limit offset :offset
"""

_NET_WORTH_TOTAL_COUNT_SQL = f"""
    select count(distinct as_of)
    from analytics_marts.mart_net_worth_daily
    {_SERIES_FILTER}
"""


def _series_params(
    since: date,
    until: date,
    account_id: str | None,
    entity_id: str | None,
    limit: int,
    offset: int,
) -> dict[str, object]:
    return {
        "since": since,
        "until": until,
        "account_id": account_id,
        "entity_id": entity_id,
        "limit": limit,
        "offset": offset,
    }


def fetch_net_worth(
    *,
    since: date,
    until: date,
    account_id: str | None,
    entity_id: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, object]], int]:
    """Return one page of account-day net-worth rows plus the total count."""
    params = _series_params(since, until, account_id, entity_id, limit, offset)
    rows = _rows(_NET_WORTH_SQL, params)
    return rows, _count(_NET_WORTH_COUNT_SQL, params)


def fetch_net_worth_total(
    *,
    since: date,
    until: date,
    account_id: str | None,
    entity_id: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, object]], int]:
    """Return one page of daily-total net-worth rows plus the total count."""
    params = _series_params(since, until, account_id, entity_id, limit, offset)
    rows = _rows(_NET_WORTH_TOTAL_SQL, params)
    return rows, _count(_NET_WORTH_TOTAL_COUNT_SQL, params)


# ---------------------------------------------------------------------------
# Cashflow
# ---------------------------------------------------------------------------

_CASHFLOW_SQL = f"""
    select
        as_of,
        entity_id::text as entity_id,
        account_id::text as account_id,
        account_currency,
        inflow_acct_ccy,
        outflow_acct_ccy,
        net_acct_ccy,
        inflow_eur,
        outflow_eur,
        net_eur,
        inflow_dkk,
        outflow_dkk,
        net_dkk
    from analytics_marts.mart_cashflow_daily
    {_SERIES_FILTER}
    order by as_of, account_id
    limit :limit offset :offset
"""

_CASHFLOW_COUNT_SQL = f"""
    select count(*)
    from analytics_marts.mart_cashflow_daily
    {_SERIES_FILTER}
"""


def fetch_cashflow(
    *,
    since: date,
    until: date,
    account_id: str | None,
    entity_id: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, object]], int]:
    """Return one page of account-day cashflow rows plus the total count."""
    params = _series_params(since, until, account_id, entity_id, limit, offset)
    rows = _rows(_CASHFLOW_SQL, params)
    return rows, _count(_CASHFLOW_COUNT_SQL, params)


# ---------------------------------------------------------------------------
# Household reporting (#333, ADR-0052)
# ---------------------------------------------------------------------------

_HOUSEHOLD_CATEGORIES_SQL = """
    select
        category_id::text as category_id,
        parent_id::text as parent_id,
        name,
        kind,
        sort_order,
        archived,
        revision
    from analytics_staging.stg_raw__household_category
    order by sort_order, name, category_id
"""


def fetch_household_categories() -> list[dict[str, object]]:
    """Return the complete category tree, including archived historical nodes."""
    return _rows(_HOUSEHOLD_CATEGORIES_SQL, {})


_HOUSEHOLD_DEFAULT_ACCOUNTS_SQL = """
    select a.id::text as account_id
    from account as a
    where a.kind = 'checking'
      and (
          cardinality(cast(:entity_ids as text[])) = 0
          or a.entity_id::text = any(cast(:entity_ids as text[]))
      )
    order by a.id
"""


def fetch_household_default_accounts(*, entity_ids: list[str]) -> list[str]:
    """Resolve the default checking-account scope for selected household members."""
    rows = _rows(_HOUSEHOLD_DEFAULT_ACCOUNTS_SQL, {"entity_ids": entity_ids})
    return [str(row["account_id"]) for row in rows]


_HOUSEHOLD_CHECKING_ACCOUNTS_SQL = """
    select a.id::text as account_id
    from account as a
    where a.kind = 'checking'
      and a.id::text = any(cast(:account_ids as text[]))
      and (
          cardinality(cast(:entity_ids as text[])) = 0
          or a.entity_id::text = any(cast(:entity_ids as text[]))
      )
    order by a.id
"""


def fetch_household_checking_accounts(
    *,
    account_ids: list[str],
    entity_ids: list[str],
) -> list[str]:
    """Return selected ids that belong to the eligible checking-account scope."""
    if not account_ids:
        return []
    rows = _rows(
        _HOUSEHOLD_CHECKING_ACCOUNTS_SQL,
        {"account_ids": account_ids, "entity_ids": entity_ids},
    )
    return [str(row["account_id"]) for row in rows]


_HOUSEHOLD_FACTS_SQL = """
    select
        f.transaction_id::text as transaction_id,
        f.account_id::text as account_id,
        f.entity_id::text as entity_id,
        f.account_currency,
        f.as_of,
        f.transaction_created_at,
        f.source_amount_native,
        f.allocation_amount_native,
        f.treatment,
        f.category_id::text as category_id,
        f.category_name,
        f.category_kind,
        f.category_parent_id::text as category_parent_id,
        f.counterparty,
        f.description,
        f.classification_source_current,
        f.source_snapshot_drift,
        f.classification_review_state,
        f.allocation_mismatch,
        f.allocation_amount_eur,
        f.allocation_amount_dkk,
        f.is_default_scope
    from analytics_marts.fct_household_report_allocation as f
    where f.as_of >= :since
      and f.as_of <= :until
      and f.account_id::text = any(cast(:account_ids as text[]))
      and (
          cardinality(cast(:entity_ids as text[])) = 0
          or f.entity_id::text = any(cast(:entity_ids as text[]))
      )
    order by f.as_of, f.transaction_id, f.category_id nulls first
"""


def fetch_household_report_facts(
    *,
    since: date,
    until: date,
    account_ids: list[str],
    entity_ids: list[str],
) -> list[dict[str, object]]:
    """Return signed allocation facts for selected bank transactions only."""
    return _rows(
        _HOUSEHOLD_FACTS_SQL,
        {
            "since": since,
            "until": until,
            "account_ids": account_ids,
            "entity_ids": entity_ids,
        },
    )


_HOUSEHOLD_TRANSACTION_CANDIDATES = """
    select
        f.transaction_id,
        max(f.as_of) as as_of
    from analytics_marts.fct_household_report_allocation as f
    where f.as_of >= :since
      and f.as_of <= :until
      and f.account_id::text = any(cast(:account_ids as text[]))
      and (
          cardinality(cast(:entity_ids as text[])) = 0
          or f.entity_id::text = any(cast(:entity_ids as text[]))
      )
      and (
          not :category_filter
          or exists (
              select 1
              from analytics_marts.fct_household_report_allocation as selected
              where selected.transaction_id = f.transaction_id
                and selected.category_id::text = any(cast(:category_ids as text[]))
          )
      )
      and (
          :search is null
          or position(lower(:search) in lower(concat_ws(
              ' ',
              f.counterparty,
              f.description,
              f.category_name
          ))) > 0
          or exists (
              select 1
              from analytics_staging.stg_raw__household_payment_detail_link as link
              inner join analytics_staging.stg_raw__household_payment_detail as detail
                  on link.detail_id = detail.detail_id
              where link.transaction_id = f.transaction_id
                and detail.provider = 'paypal'
                and position(lower(:search) in lower(concat_ws(
                    ' ',
                    detail.merchant_name,
                    detail.reference,
                    detail.external_reference
                ))) > 0
          )
      )
    group by f.transaction_id
"""

_HOUSEHOLD_TRANSACTION_PAGE_SQL = f"""
    with candidates as (
        {_HOUSEHOLD_TRANSACTION_CANDIDATES}
    ),
    page as (
        select candidate.transaction_id
        from candidates as candidate
        order by candidate.as_of desc, candidate.transaction_id desc
        limit :limit offset :offset
    )
    select
        f.transaction_id::text as transaction_id,
        f.account_id::text as account_id,
        f.entity_id::text as entity_id,
        f.account_currency,
        f.as_of,
        f.transaction_created_at,
        f.source_amount_native,
        f.allocation_amount_native,
        f.treatment,
        f.category_id::text as category_id,
        f.category_name,
        f.category_kind,
        f.category_parent_id::text as category_parent_id,
        f.counterparty,
        f.description,
        f.classification_source_current,
        f.source_snapshot_drift,
        f.classification_review_state,
        f.allocation_mismatch,
        f.allocation_amount_eur,
        f.allocation_amount_dkk,
        f.is_default_scope
    from page
    inner join analytics_marts.fct_household_report_allocation as f
        on page.transaction_id = f.transaction_id
    order by f.as_of desc, f.transaction_id desc, f.category_id nulls first
"""

_HOUSEHOLD_TRANSACTION_COUNT_SQL = f"""
    with candidates as (
        {_HOUSEHOLD_TRANSACTION_CANDIDATES}
    )
    select count(*) from candidates
"""


def fetch_household_transaction_page(
    *,
    since: date,
    until: date,
    account_ids: list[str],
    entity_ids: list[str],
    category_ids: list[str],
    category_filter: bool,
    search: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, object]], int]:
    """Return one stable bank-transaction page and the filtered transaction count."""
    params = {
        "since": since,
        "until": until,
        "account_ids": account_ids,
        "entity_ids": entity_ids,
        "category_ids": category_ids,
        "category_filter": category_filter,
        "search": search.casefold() if search is not None else None,
        "limit": limit,
        "offset": offset,
    }
    rows = _rows(_HOUSEHOLD_TRANSACTION_PAGE_SQL, params)
    count = _count(_HOUSEHOLD_TRANSACTION_COUNT_SQL, params)
    return rows, count


_HOUSEHOLD_PAYMENT_DETAILS_SQL = """
    select
        link.transaction_id::text as transaction_id,
        detail.detail_id::text as detail_id,
        detail.external_reference,
        detail.reference,
        detail.merchant_name,
        detail.event_kind,
        detail.amount_native as source_amount,
        detail.currency as source_currency,
        (detail.ts at time zone 'UTC')::date as source_date,
        detail.source_fields ->> 'merchant_category_code' as merchant_category_code,
        detail.source_fields ->> 'bank_code' as bank_code,
        detail.source_fields ->> 'bank_sub_code' as bank_sub_code,
        link.bank_amount,
        link.detail_revision as approved_detail_revision,
        detail.revision as current_detail_revision
    from analytics_staging.stg_raw__household_payment_detail_link as link
    inner join analytics_staging.stg_raw__household_payment_detail as detail
        on link.detail_id = detail.detail_id
    where detail.provider = 'paypal'
      and link.transaction_id::text = any(cast(:transaction_ids as text[]))
    order by link.transaction_id, detail.detail_id
"""


def fetch_household_payment_details(*, transaction_ids: list[str]) -> list[dict[str, object]]:
    """Return minimal whitelisted PayPal detail linked to selected bank rows."""
    if not transaction_ids:
        return []
    return _rows(_HOUSEHOLD_PAYMENT_DETAILS_SQL, {"transaction_ids": transaction_ids})


_HOUSEHOLD_UNMATCHED_DETAILS_SQL = """
    select count(*)
    from analytics_staging.stg_raw__household_payment_detail as detail
    where detail.provider = 'paypal'
      and (detail.ts at time zone 'UTC')::date >= :since
      and (detail.ts at time zone 'UTC')::date <= :until
      and not exists (
          select 1
          from analytics_staging.stg_raw__household_payment_detail_link as link
          where link.detail_id = detail.detail_id
      )
      and (
          cardinality(cast(:entity_ids as text[])) = 0
          or exists (
              select 1
              from bank_connection as connection
              inner join entity as owner on owner.name = connection.entity_name
              where connection.id = detail.connection_id
                and owner.id::text = any(cast(:entity_ids as text[]))
          )
      )
"""


def fetch_household_unmatched_payment_detail_count(
    *,
    since: date,
    until: date,
    entity_ids: list[str],
) -> int:
    """Count unlinked PayPal details for a date/member scope, never as expenses."""
    return _count(
        _HOUSEHOLD_UNMATCHED_DETAILS_SQL,
        {"since": since, "until": until, "entity_ids": entity_ids},
    )


_HOUSEHOLD_SOURCE_FRESHNESS_SQL = """
    select
        min(f.as_of) as history_start,
        max(f.as_of) as latest_bank_booking_date,
        max(f.transaction_created_at) as latest_bank_import_at
    from analytics_marts.fct_household_report_allocation as f
    where f.account_id::text = any(cast(:account_ids as text[]))
      and (
          cardinality(cast(:entity_ids as text[])) = 0
          or f.entity_id::text = any(cast(:entity_ids as text[]))
      )
"""

_HOUSEHOLD_FX_FRESHNESS_SQL = """
    select max(f.as_of) as latest_fx_rate_date
    from analytics_staging.stg_raw__fx_rate as f
    where f.base_ccy = 'EUR'
      and f.quote_ccy = 'DKK'
      and f.as_of <= :until
"""

_HOUSEHOLD_DETAIL_FRESHNESS_SQL = """
    select max(connection.last_sync_at) as latest_payment_detail_sync_at
    from bank_connection as connection
    where connection.provider = 'paypal'
      and connection.last_sync_status = 'ok'
      and (
          cardinality(cast(:entity_ids as text[])) = 0
          or exists (
              select 1
              from entity as owner
              where owner.name = connection.entity_name
                and owner.id::text = any(cast(:entity_ids as text[]))
          )
      )
"""


def fetch_household_report_freshness(
    *, account_ids: list[str], entity_ids: list[str], until: date
) -> dict[str, object]:
    """Return observed history and source freshness without claiming completeness."""
    rows = _rows(
        _HOUSEHOLD_SOURCE_FRESHNESS_SQL,
        {"account_ids": account_ids, "entity_ids": entity_ids},
    )
    fx_rows = _rows(_HOUSEHOLD_FX_FRESHNESS_SQL, {"until": until})
    detail_rows = _rows(_HOUSEHOLD_DETAIL_FRESHNESS_SQL, {"entity_ids": entity_ids})
    return {
        **rows[0],
        **fx_rows[0],
        **detail_rows[0],
    }


# ---------------------------------------------------------------------------
# Allocation (latest day, joined with the account dimension)
# ---------------------------------------------------------------------------

_ALLOCATION_SQL = """
    with latest as (
        select max(as_of) as as_of
        from analytics_marts.mart_net_worth_daily
    )

    select
        nw.as_of,
        nw.balance_eur,
        nw.balance_dkk,
        e.name as entity_name,
        a.currency as account_currency,
        a.kind as account_kind
    from analytics_marts.mart_net_worth_daily as nw
    inner join latest on nw.as_of = latest.as_of
    inner join account as a on a.id::text = nw.account_id::text
    inner join entity as e on e.id = a.entity_id
"""


def fetch_allocation_rows() -> list[dict[str, object]]:
    """Return latest-day balances joined with the grouping dimensions."""
    return _rows(_ALLOCATION_SQL, {})


# ---------------------------------------------------------------------------
# Accounts dimension
# ---------------------------------------------------------------------------

_ACCOUNTS_SQL = """
    with account_updates as (
        select account_id, max(created_at) as updated_at
        from "transaction"
        group by account_id
        union all
        select account_id, max(created_at) as updated_at
        from holding_snapshot
        group by account_id
        union all
        select account_id, max(created_at) as updated_at
        from document
        where account_id is not null
        group by account_id
        union all
        -- A repeated staged import updates existing raw rows, retaining their
        -- original created_at. Use the successful commit time for each account
        -- actually represented by an included row in that session.
        select a.id as account_id, max(s.committed_at) as updated_at
        from import_session as s
        inner join import_row as r on r.session_id = s.id
        inner join account as a
            on a.provider = 'nordnet'
            and a.external_id = case
                when s.source = 'nordnet_transactions'
                     and r.kind = 'transaction'
                    then r.payload ->> 'account_number'
                when s.source = 'nordnet_holdings'
                     and r.kind = 'holding'
                    then s.params ->> 'account_number'
            end
        where s.status = 'committed'
          and s.committed_at is not null
          and not r.excluded
        group by a.id
        union all
        -- A header-only holdings export is a valid complete empty snapshot.
        select a.id as account_id, max(s.committed_at) as updated_at
        from import_session as s
        inner join account as a
            on a.provider = 'nordnet'
            and a.external_id = (s.params ->> 'account_number')
        where s.source = 'nordnet_holdings'
          and s.status = 'committed'
          and s.committed_at is not null
          and (s.params ->> 'empty_snapshot_confirmed') = 'true'
          and not exists (
              select 1 from import_row as r where r.session_id = s.id
          )
        group by a.id
    ),
    latest_account_updates as (
        select account_id, max(updated_at) as last_updated_at
        from account_updates
        group by account_id
    ),
    daily_balances as (
        select
            account_id::text as account_id,
            as_of,
            balance_acct_ccy,
            lag(balance_acct_ccy) over (partition by account_id order by as_of) as prev_balance
        from analytics_marts.mart_net_worth_daily
    ),
    balance_changes as (
        -- The first observed balance counts as a change, so an account
        -- whose balance never moved reports the date it first appeared.
        select account_id, max(as_of) as balance_changed_on
        from daily_balances
        where prev_balance is null or balance_acct_ccy is distinct from prev_balance
        group by account_id
    )
    select
        a.id::text as account_id,
        a.entity_id::text as entity_id,
        e.name as entity_name,
        a.provider,
        a.name,
        a.kind,
        a.currency,
        a.iban,
        updates.last_updated_at,
        changes.balance_changed_on
    from account as a
    inner join entity as e on e.id = a.entity_id
    left join latest_account_updates as updates on updates.account_id = a.id
    left join balance_changes as changes on changes.account_id = a.id::text
    order by e.name, a.name
"""


def fetch_accounts() -> list[dict[str, object]]:
    """Return the account dimension with the raw IBAN, import freshness, and last balance change.

    Callers (the route layer) must mask the IBAN before serialising;
    see :func:`penge.web.mask.mask_iban`.
    """
    return _rows(_ACCOUNTS_SQL, {})


# ---------------------------------------------------------------------------
# Returns (mart_returns_daily, ADR-0039)
# ---------------------------------------------------------------------------

_RETURNS_FILTER = """
    where as_of >= :since
      and as_of <= :until
      and scope = :scope
      and (cast(:scope_key as text) is null or scope_key = :scope_key)
"""

_RETURNS_SQL = f"""
    select
        as_of,
        scope,
        scope_key,
        begin_mv_eur,
        end_mv_eur,
        net_flow_eur,
        return_factor_eur,
        begin_mv_dkk,
        end_mv_dkk,
        net_flow_dkk,
        return_factor_dkk
    from analytics_marts.mart_returns_daily
    {_RETURNS_FILTER}
    order by scope_key, as_of
    limit :limit offset :offset
"""

_RETURNS_COUNT_SQL = f"""
    select count(*)
    from analytics_marts.mart_returns_daily
    {_RETURNS_FILTER}
"""


def fetch_returns(
    *,
    since: date,
    until: date,
    scope: str,
    scope_key: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, object]], int]:
    """Return one page of scope-day return rows plus the total count."""
    params: dict[str, object] = {
        "since": since,
        "until": until,
        "scope": scope,
        "scope_key": scope_key,
        "limit": limit,
        "offset": offset,
    }
    rows = _rows(_RETURNS_SQL, params)
    return rows, _count(_RETURNS_COUNT_SQL, params)


def fetch_returns_window(
    *,
    since: date,
    until: date,
    scope: str,
) -> list[dict[str, object]]:
    """Return ALL rows of one scope in the window, for summary math.

    Unpaginated by design: the summary endpoint must chain-link every
    day of the window. Row counts are bounded by days x scope keys.
    """
    params: dict[str, object] = {
        "since": since,
        "until": until,
        "scope": scope,
        "scope_key": None,
        "limit": 1_000_000,
        "offset": 0,
    }
    return _rows(_RETURNS_SQL, params)


# ---------------------------------------------------------------------------
# Benchmarks (raw price_history + instrument dimension)
# ---------------------------------------------------------------------------

_BENCHMARKS_SQL = """
    select
        i.id::text as instrument_id,
        i.name,
        i.ticker,
        max(p.currency) as currency,
        min(p.as_of) as first_as_of,
        max(p.as_of) as last_as_of,
        count(*) as points
    from price_history as p
    inner join instrument as i on i.id = p.instrument_id
    group by i.id, i.name, i.ticker
    order by i.name
"""


def fetch_benchmarks() -> list[dict[str, object]]:
    """Return every instrument that has ingested price history."""
    return _rows(_BENCHMARKS_SQL, {})


_BENCHMARK_SERIES_FILTER = """
    where p.instrument_id::text = :instrument_id
      and p.as_of >= :since
      and p.as_of <= :until
"""

_BENCHMARK_SERIES_SQL = f"""
    select
        p.as_of,
        p.close,
        p.currency
    from price_history as p
    {_BENCHMARK_SERIES_FILTER}
    order by p.as_of
    limit :limit offset :offset
"""

_BENCHMARK_SERIES_COUNT_SQL = f"""
    select count(*)
    from price_history as p
    {_BENCHMARK_SERIES_FILTER}
"""


def fetch_benchmark_series(
    *,
    instrument_id: str,
    since: date,
    until: date,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, object]], int]:
    """Return one page of daily closes for one instrument."""
    params: dict[str, object] = {
        "instrument_id": instrument_id,
        "since": since,
        "until": until,
        "limit": limit,
        "offset": offset,
    }
    rows = _rows(_BENCHMARK_SERIES_SQL, params)
    return rows, _count(_BENCHMARK_SERIES_COUNT_SQL, params)


# ---------------------------------------------------------------------------
# Fees (canonical transaction table, forward-filled ECB FX)
# ---------------------------------------------------------------------------

# Explicit fee transactions count by their amount; trade rows count by
# their `fee` column. abs() because cost legs are recorded negative.
# FX mirrors the marts: EUR via the forward-filled ECB rate of the fee
# date, DKK via the EUR bridge.
_FEES_SQL = """
    with fee_rows as (
        select
            t.account_id,
            coalesce(t.value_date, (t.ts at time zone 'UTC')::date) as as_of,
            case
                when t.kind = 'fee' then abs(t.amount)
                else abs(coalesce(t.fee, 0))
            end as fee_acct_ccy
        from "transaction" as t
        where t.kind = 'fee' or coalesce(t.fee, 0) <> 0
    ),

    converted as (
        select
            f.account_id,
            f.as_of,
            (
                f.fee_acct_ccy / nullif(
                    case
                        when a.currency = 'EUR' then 1::numeric(20, 8)
                        else (
                            select fx.rate
                            from fx_rate as fx
                            where fx.base_ccy = 'EUR'
                              and fx.quote_ccy = a.currency
                              and fx.as_of <= f.as_of
                            order by fx.as_of desc
                            limit 1
                        )
                    end, 0
                )
            ) as fee_eur
        from fee_rows as f
        inner join account as a on a.id = f.account_id
        where f.as_of >= :since
          and f.as_of <= :until
    )

    select
        extract(year from c.as_of)::int as year,
        c.account_id::text as account_id,
        sum(c.fee_eur)::numeric(20, 4) as fees_eur,
        sum(
            c.fee_eur * (
                select fx.rate
                from fx_rate as fx
                where fx.base_ccy = 'EUR'
                  and fx.quote_ccy = 'DKK'
                  and fx.as_of <= c.as_of
                order by fx.as_of desc
                limit 1
            )
        )::numeric(20, 4) as fees_dkk
    from converted as c
    group by year, c.account_id
    order by year, c.account_id
"""


def fetch_fees(*, since: date, until: date) -> list[dict[str, object]]:
    """Return yearly fee totals per account in EUR and DKK."""
    return _rows(_FEES_SQL, {"since": since, "until": until})


# ---------------------------------------------------------------------------
# Freshness metadata
# ---------------------------------------------------------------------------

_FRESHNESS_SQL_TEMPLATE = """
    select max(as_of) as latest_as_of, count(*) as row_count
    from analytics_marts.{mart}
"""

_MARTS = (
    "mart_net_worth_daily",
    "mart_cashflow_daily",
    "mart_returns_daily",
    "mart_household_report_daily",
)


def fetch_freshness() -> list[dict[str, object]]:
    """Return latest data date and row count for each served mart."""
    out: list[dict[str, object]] = []
    for mart in _MARTS:
        # `mart` comes from the closed _MARTS tuple above, never from
        # request input, so the format() below cannot inject SQL.
        row = _rows(_FRESHNESS_SQL_TEMPLATE.format(mart=mart), {})[0]
        out.append({"mart": mart, **row})
    return out
