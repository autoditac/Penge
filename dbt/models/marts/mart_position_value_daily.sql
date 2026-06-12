{{ config(materialized='table') }}

-- Daily forward-filled position values per (account, instrument), in
-- account currency, EUR, and DKK.
--
-- Mechanics (extracted from `mart_net_worth_daily`, see ADR-0039):
--   1. Build a daily date spine spanning the active range of
--      `raw.holding_snapshot` (min..max as_of).
--   2. For each (account, instrument) pair ever observed, forward-fill
--      the most recent `market_value` snapshot at-or-before each spine
--      date. Days before the first snapshot of a pair carry 0. Cash is
--      a synthetic instrument with `kind = 'cash'` per ADR-0008, so the
--      panel covers cash and securities alike.
--   3. Convert to EUR and DKK with the spine-date ECB FX rate
--      (`raw.fx_rate`, base_ccy = 'EUR'), forward-filled across
--      weekends/holidays, using the account currency.
--
-- `mart_net_worth_daily` aggregates this mart per account;
-- `mart_returns_daily` aggregates it per return scope. Keeping one
-- panel guarantees the position, account, and returns views add up.
--
-- See issue #205 and ADR-0039.

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
    p.account_id,
    p.instrument_id,
    i.kind as instrument_kind,
    a.currency as account_currency,
    p.as_of,
    coalesce(p.market_value, 0)::numeric(20, 4) as mv_acct_ccy,
    (
        coalesce(p.market_value, 0) / nullif(fx_acct.eur_to_ccy, 0)
    )::numeric(20, 4) as mv_eur,
    (
        coalesce(p.market_value, 0)
        / nullif(fx_acct.eur_to_ccy, 0)
        * fx_dkk.eur_to_ccy
    )::numeric(20, 4) as mv_dkk
from panel as p
inner join {{ source('raw', 'account') }} as a on p.account_id = a.id
inner join {{ source('raw', 'instrument') }} as i on p.instrument_id = i.id
left join fx_eur_panel as fx_acct
    on
        p.as_of = fx_acct.as_of
        and a.currency = fx_acct.currency
left join fx_eur_panel as fx_dkk
    on
        p.as_of = fx_dkk.as_of
        and fx_dkk.currency = 'DKK'
