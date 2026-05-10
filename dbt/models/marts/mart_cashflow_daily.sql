{{ config(materialized='table') }}

-- Daily cashflow time series per account, valued in account currency,
-- EUR, and DKK.
--
-- Mechanics:
--   1. Bucket every `raw.transaction` row by `coalesce(value_date,
--      (ts at time zone 'UTC')::date)` — the value date is the
--      calendar day on which money hit/left the account. `ts` is only
--      used as a fallback when providers omit `value_date`; we cast
--      via UTC because `ts` is `TIMESTAMP WITH TIME ZONE` and a naive
--      `::date` would depend on the session time zone.
--   2. Split the signed `amount` column into inflow / outflow halves.
--      `amount > 0` → inflow, `amount < 0` → outflow (taken as the
--      absolute value). Net = inflow - outflow.
--   3. Sum per (account_id, as_of) to get one row per account-day.
--   4. Convert to EUR via the value-date ECB FX rate (forward-filled
--      across weekends/holidays in `raw.fx_rate`, base_ccy = 'EUR'),
--      then EUR → DKK using the same panel as a bridge currency. This
--      mirrors the FX strategy in `mart_net_worth_daily` so the two
--      marts agree on a single FX source.
--
-- Days with no transactions for an account simply produce no row — the
-- consumer (e.g. `query_cashflow` in apps/mcp) is responsible for
-- treating absent days as zero when rolling up to coarser granularity.
--
-- See issue #46 and ADR-0008.

with
txns as (
    select
        t.account_id,
        t.amount,
        coalesce(t.value_date, (t.ts at time zone 'UTC')::date) as as_of
    from {{ source('raw', 'transaction') }} as t
),

agg as (
    select
        account_id,
        as_of,
        sum(case when amount > 0 then amount else 0 end)::numeric(20, 4)
            as inflow_acct_ccy,
        sum(case when amount < 0 then -amount else 0 end)::numeric(20, 4)
            as outflow_acct_ccy
    from txns
    group by account_id, as_of
),

fx as (
    select
        a.id as account_id,
        a.entity_id,
        a.currency as account_currency,
        agg.as_of,
        case
            when a.currency = 'EUR' then 1::numeric(20, 8)
            else (
                select fx_acct.rate
                from {{ source('raw', 'fx_rate') }} as fx_acct
                where
                    fx_acct.base_ccy = 'EUR'
                    and fx_acct.quote_ccy = a.currency
                    and fx_acct.as_of <= agg.as_of
                order by fx_acct.as_of desc
                limit 1
            )
        end as eur_to_acct,
        (
            select fx_dkk.rate
            from {{ source('raw', 'fx_rate') }} as fx_dkk
            where
                fx_dkk.base_ccy = 'EUR'
                and fx_dkk.quote_ccy = 'DKK'
                and fx_dkk.as_of <= agg.as_of
            order by fx_dkk.as_of desc
            limit 1
        ) as eur_to_dkk
    from agg
    inner join {{ source('raw', 'account') }} as a on agg.account_id = a.id
)

select
    fx.entity_id,
    fx.account_id,
    fx.account_currency,
    agg.as_of,
    agg.inflow_acct_ccy,
    agg.outflow_acct_ccy,
    (agg.inflow_acct_ccy - agg.outflow_acct_ccy)::numeric(20, 4)
        as net_acct_ccy,
    (agg.inflow_acct_ccy / nullif(fx.eur_to_acct, 0))::numeric(20, 4)
        as inflow_eur,
    (agg.outflow_acct_ccy / nullif(fx.eur_to_acct, 0))::numeric(20, 4)
        as outflow_eur,
    (
        (agg.inflow_acct_ccy - agg.outflow_acct_ccy)
        / nullif(fx.eur_to_acct, 0)
    )::numeric(20, 4) as net_eur,
    (
        agg.inflow_acct_ccy
        / nullif(fx.eur_to_acct, 0)
        * fx.eur_to_dkk
    )::numeric(20, 4) as inflow_dkk,
    (
        agg.outflow_acct_ccy
        / nullif(fx.eur_to_acct, 0)
        * fx.eur_to_dkk
    )::numeric(20, 4) as outflow_dkk,
    (
        (agg.inflow_acct_ccy - agg.outflow_acct_ccy)
        / nullif(fx.eur_to_acct, 0)
        * fx.eur_to_dkk
    )::numeric(20, 4) as net_dkk
from agg
inner join fx on agg.account_id = fx.account_id and agg.as_of = fx.as_of
