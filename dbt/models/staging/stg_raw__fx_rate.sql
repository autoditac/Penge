{{ config(materialized='view') }}

-- Pass-through staging view for `raw.fx_rate`.
--
-- ECB-style daily rates, base/quote pair per row. Sparse on
-- weekends/holidays; the no-gap invariant is enforced by the
-- `mart_net_worth_daily__no_fx_gaps` custom test.

with source as (
    select
        id as fx_rate_id,
        as_of,
        base_ccy,
        quote_ccy,
        rate,
        source as rate_source,
        created_at
    from {{ source('raw', 'fx_rate') }}
),

final as (
    select * from source
)

select * from final
