{{ config(materialized='view') }}

-- Pass-through staging view for `raw.price_history`.
--
-- Daily close per instrument, denominated in the instrument's
-- currency (column `currency`). Sparse on weekends/holidays — marts
-- that need a daily series should forward-fill via a date spine.

with source as (
    select
        id as price_history_id,
        instrument_id,
        as_of,
        close as close_amount_native,
        currency,
        source as price_source,
        created_at
    from {{ source('raw', 'price_history') }}
),

final as (
    select * from source
)

select * from final
