{{ config(materialized='view') }}

-- Pass-through staging view for `raw.price_history`.
--
-- Daily close per instrument, denominated in the instrument's
-- currency (column `currency`). Sparse on weekends/holidays — marts
-- that need a daily series should forward-fill via a date spine.

with final as (
    select
        p.id as price_history_id,
        p.instrument_id,
        p.as_of,
        p.close as close_amount_native,
        p.currency,
        p.source as price_source,
        p.created_at
    from {{ source('raw', 'price_history') }} as p
)

select * from final
