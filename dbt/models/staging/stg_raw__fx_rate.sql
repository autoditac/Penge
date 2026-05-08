{{ config(materialized='view') }}

-- Pass-through staging view for `raw.fx_rate`.
--
-- ECB-style daily rates, base/quote pair per row. Sparse on
-- weekends/holidays; the no-gap invariant is enforced by the
-- `mart_net_worth_daily__no_fx_gaps` custom test.

with final as (
    select
        f.id as fx_rate_id,
        f.as_of,
        f.base_ccy,
        f.quote_ccy,
        f.rate,
        f.source as rate_source,
        f.created_at
    from {{ source('raw', 'fx_rate') }} as f
)

select * from final
