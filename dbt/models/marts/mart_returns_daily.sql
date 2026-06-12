{{ config(materialized='table') }}

-- Daily time-weighted return factors per scope, measured in EUR and in
-- DKK. One row per (scope, scope_key, as_of):
--
--   scope = 'account'     scope_key = account id
--   scope = 'asset_class' scope_key = instrument.kind (cash, fund, ...)
--   scope = 'household'   scope_key = 'household'
--
-- Mechanics (see ADR-0039):
--   1. Aggregate `mart_position_value_daily` per scope and day to get
--      end-of-day values; the previous day's value is the begin value.
--   2. Convert external flows (raw.transaction) at the flow-date ECB
--      rate, forward-filled, account currency -> EUR -> DKK.
--   3. Daily factor with start-of-day flows:
--      factor = end_mv / (begin_mv + net_flow), NULL when the
--      denominator is <= 0 (no capital at risk that day).
--
-- External flows per scope:
--   - account:   deposit, withdrawal, internal_transfer (as recorded).
--   - household: deposit, withdrawal (internal transfers net out).
--     Fees and taxes are NOT flows at these scopes, so account and
--     household returns are net of costs as recorded.
--   - asset_class: instrument-linked transactions move value between
--     the instrument's class and the account's *attribution class*
--     (the cash class when the account has a cash position, else the
--     class of its earliest-snapshotted instrument, e.g. PFA/Growney
--     fund-only accounts). `cash_interest` is the cash class's return,
--     and instrument-less dividends on fund-attributed accounts are
--     the fund's return — neither is a flow.
--
-- Days outside the holding-snapshot spine produce no row; flows dated
-- outside the spine are not considered.
--
-- See issue #205 and ADR-0039.

with
scope_values as (
    select
        'account' as scope,
        account_id::text as scope_key,
        as_of,
        sum(mv_eur) as end_mv_eur,
        sum(mv_dkk) as end_mv_dkk
    from {{ ref('mart_position_value_daily') }}
    group by account_id, as_of

    union all

    select
        'asset_class' as scope,
        instrument_kind as scope_key,
        as_of,
        sum(mv_eur) as end_mv_eur,
        sum(mv_dkk) as end_mv_dkk
    from {{ ref('mart_position_value_daily') }}
    group by instrument_kind, as_of

    union all

    select
        'household' as scope,
        'household' as scope_key,
        as_of,
        sum(mv_eur) as end_mv_eur,
        sum(mv_dkk) as end_mv_dkk
    from {{ ref('mart_position_value_daily') }}
    group by as_of
),

flows_raw as (
    select
        t.account_id,
        t.kind,
        t.amount,
        i.kind as instrument_kind,
        coalesce(t.value_date, (t.ts at time zone 'UTC')::date) as as_of
    from {{ source('raw', 'transaction') }} as t
    left join {{ source('raw', 'instrument') }} as i
        on t.instrument_id = i.id
    where t.amount is not null
),

flows_fx as (
    select
        f.account_id,
        f.kind,
        f.instrument_kind,
        f.as_of,
        (
            f.amount / nullif(
                case
                    when a.currency = 'EUR' then 1::numeric(20, 8)
                    else (
                        select fx.rate
                        from {{ source('raw', 'fx_rate') }} as fx
                        where
                            fx.base_ccy = 'EUR'
                            and fx.quote_ccy = a.currency
                            and fx.as_of <= f.as_of
                        order by fx.as_of desc
                        limit 1
                    )
                end, 0
            )
        )::numeric(20, 4) as amount_eur
    from flows_raw as f
    inner join {{ source('raw', 'account') }} as a on f.account_id = a.id
),

eur_dkk as (
    select
        f.account_id,
        f.kind,
        f.instrument_kind,
        f.as_of,
        f.amount_eur,
        (
            f.amount_eur * (
                select fx.rate
                from {{ source('raw', 'fx_rate') }} as fx
                where
                    fx.base_ccy = 'EUR'
                    and fx.quote_ccy = 'DKK'
                    and fx.as_of <= f.as_of
                order by fx.as_of desc
                limit 1
            )
        )::numeric(20, 4) as amount_dkk
    from flows_fx as f
),

-- The account's attribution class for instrument-less cash legs:
-- 'cash' when a cash position was ever snapshotted, otherwise the
-- earliest-snapshotted instrument kind (alphabetical tie-break).
attribution as (
    select distinct on (hs.account_id)
        hs.account_id,
        i.kind as attribution_kind
    from {{ source('raw', 'holding_snapshot') }} as hs
    inner join {{ source('raw', 'instrument') }} as i
        on hs.instrument_id = i.id
    order by
        hs.account_id asc,
        (i.kind = 'cash') desc,
        hs.as_of asc,
        i.kind asc
),

scope_flows as (
    -- account scope: external money crossing the account boundary
    select
        'account' as scope,
        f.account_id::text as scope_key,
        f.as_of,
        sum(f.amount_eur) as net_flow_eur,
        sum(f.amount_dkk) as net_flow_dkk
    from eur_dkk as f
    where f.kind in ('deposit', 'withdrawal', 'internal_transfer')
    group by f.account_id, f.as_of

    union all

    -- household scope: internal transfers net out and are excluded
    select
        'household' as scope,
        'household' as scope_key,
        f.as_of,
        sum(f.amount_eur) as net_flow_eur,
        sum(f.amount_dkk) as net_flow_dkk
    from eur_dkk as f
    where f.kind in ('deposit', 'withdrawal')
    group by f.as_of

    union all

    -- asset-class scope, leg 1: value entering/leaving the linked
    -- instrument's class (a buy has a negative cash amount, hence a
    -- positive flow into the class; dividends leave the class as cash)
    select
        'asset_class' as scope,
        f.instrument_kind as scope_key,
        f.as_of,
        sum(-f.amount_eur) as net_flow_eur,
        sum(-f.amount_dkk) as net_flow_dkk
    from eur_dkk as f
    where
        f.instrument_kind is not null
        and f.instrument_kind != 'cash'
    group by f.instrument_kind, f.as_of

    union all

    -- asset-class scope, leg 2: the cash leg of every transaction,
    -- attributed to the account's attribution class. cash_interest is
    -- the cash class's return; instrument-less dividends on non-cash
    -- attributed accounts (PFA-style returns) are that class's return.
    select
        'asset_class' as scope,
        att.attribution_kind as scope_key,
        f.as_of,
        sum(f.amount_eur) as net_flow_eur,
        sum(f.amount_dkk) as net_flow_dkk
    from eur_dkk as f
    inner join attribution as att on f.account_id = att.account_id
    where
        f.kind != 'cash_interest'
        and not (
            att.attribution_kind != 'cash'
            and f.kind = 'dividend'
            and coalesce(f.instrument_kind, 'cash') = 'cash'
        )
    group by att.attribution_kind, f.as_of
),

scope_flows_agg as (
    select
        scope,
        scope_key,
        as_of,
        sum(net_flow_eur) as net_flow_eur,
        sum(net_flow_dkk) as net_flow_dkk
    from scope_flows
    group by scope, scope_key, as_of
),

joined as (
    select
        v.scope,
        v.scope_key,
        v.as_of,
        v.end_mv_eur,
        v.end_mv_dkk,
        lag(v.end_mv_eur, 1, 0::numeric)
            over (partition by v.scope, v.scope_key order by v.as_of)
            as begin_mv_eur,
        coalesce(f.net_flow_eur, 0) as net_flow_eur,
        lag(v.end_mv_dkk, 1, 0::numeric)
            over (partition by v.scope, v.scope_key order by v.as_of)
            as begin_mv_dkk,
        coalesce(f.net_flow_dkk, 0) as net_flow_dkk
    from scope_values as v
    left join scope_flows_agg as f
        on
            v.scope = f.scope
            and v.scope_key = f.scope_key
            and v.as_of = f.as_of
)

select
    scope,
    scope_key,
    as_of,
    begin_mv_eur::numeric(20, 4) as begin_mv_eur,
    end_mv_eur::numeric(20, 4) as end_mv_eur,
    net_flow_eur::numeric(20, 4) as net_flow_eur,
    begin_mv_dkk::numeric(20, 4) as begin_mv_dkk,
    end_mv_dkk::numeric(20, 4) as end_mv_dkk,
    net_flow_dkk::numeric(20, 4) as net_flow_dkk,
    case
        when (begin_mv_eur + net_flow_eur) > 0
            then
                (end_mv_eur / (begin_mv_eur + net_flow_eur))
                ::numeric(20, 10)
    end as return_factor_eur,
    case
        when (begin_mv_dkk + net_flow_dkk) > 0
            then
                (end_mv_dkk / (begin_mv_dkk + net_flow_dkk))
                ::numeric(20, 10)
    end as return_factor_dkk
from joined
