{{ config(materialized='table') }}

-- Daily net-worth time series per account, valued in account currency,
-- EUR, and DKK.
--
-- Mechanics:
--   1. Build a daily date spine spanning the active range of
--      `raw.holding_snapshot` (min..max as_of).
--   2. For each (account, instrument) pair ever observed, forward-fill
--      the most recent `market_value` snapshot at-or-before each spine
--      date. Cash is materialised as `instrument.kind = 'cash'`
--      synthetic instruments with `quantity = saldo`, `price = 1` per
--      ADR-0008, so the same panel covers cash and securities.
--   3. Sum per (account, as_of) to get the account-currency balance.
--   4. Convert to EUR and DKK using the snapshot-date ECB FX rate
--      (`raw.fx_rate`, base_ccy = 'EUR'), forward-filled across
--      weekends/holidays so every spine date has a non-null rate
--      whenever the source has at least one rate at-or-before it.
--
-- See issue #24 and ADR-0008.
--
-- v1 scope: balance time series only. Per-transaction cashflow FX
-- attribution is intentionally out of scope here; a follow-up cashflow
-- mart will use `transaction.fx_rate` for that view.

with
date_bounds as (
    select
        min(as_of) as min_d,
        max(as_of) as max_d
    from {{ source('raw', 'holding_snapshot') }}
),

date_spine as (
    select generate_series(min_d, max_d, interval '1 day')::date as as_of
    from date_bounds
),

account_instrument as (
    select distinct
        account_id,
        instrument_id
    from {{ source('raw', 'holding_snapshot') }}
),

panel as (
    select
        ai.account_id,
        ai.instrument_id,
        ds.as_of,
        (
            select hs.market_value
            from {{ source('raw', 'holding_snapshot') }} as hs
            where
                hs.account_id = ai.account_id
                and hs.instrument_id = ai.instrument_id
                and hs.as_of <= ds.as_of
            order by hs.as_of desc
            limit 1
        ) as market_value
    from account_instrument as ai
    cross join date_spine as ds
),

balances_acct as (
    select
        p.account_id,
        p.as_of,
        coalesce(sum(p.market_value), 0)::numeric(20, 4) as balance_acct_ccy
    from panel as p
    group by p.account_id, p.as_of
),

currencies as (
    select distinct currency as code from {{ source('raw', 'account') }}
    union
    select 'EUR' as code
    union
    select 'DKK' as code
),

fx_eur_panel as (
    select
        ds.as_of,
        ccy.code as currency,
        case
            when ccy.code = 'EUR' then 1::numeric(20, 8)
            else (
                select fx.rate
                from {{ source('raw', 'fx_rate') }} as fx
                where
                    fx.base_ccy = 'EUR'
                    and fx.quote_ccy = ccy.code
                    and fx.as_of <= ds.as_of
                order by fx.as_of desc
                limit 1
            )
        end as eur_to_ccy
    from date_spine as ds
    cross join currencies as ccy
)

select
    a.entity_id,
    b.account_id,
    a.currency as account_currency,
    b.as_of,
    b.balance_acct_ccy,
    (b.balance_acct_ccy / nullif(fx_acct.eur_to_ccy, 0))::numeric(20, 4)
        as balance_eur,
    (
        b.balance_acct_ccy
        / nullif(fx_acct.eur_to_ccy, 0)
        * fx_dkk.eur_to_ccy
    )::numeric(20, 4) as balance_dkk
from balances_acct as b
inner join {{ source('raw', 'account') }} as a on b.account_id = a.id
left join fx_eur_panel as fx_acct
    on
        b.as_of = fx_acct.as_of
        and a.currency = fx_acct.currency
left join fx_eur_panel as fx_dkk
    on
        b.as_of = fx_dkk.as_of
        and fx_dkk.currency = 'DKK'
