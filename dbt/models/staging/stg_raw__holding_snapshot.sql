{{ config(materialized='view') }}

-- Pass-through staging view for `raw.holding_snapshot`.
--
-- Renames the surrogate primary key to `holding_snapshot_id` and
-- normalises money columns. The unique grain
-- (`account_id`, `instrument_id`, `as_of`) is enforced upstream by
-- a Postgres unique constraint and re-asserted as a dbt test below.

with source as (
    select
        id as holding_snapshot_id,
        account_id,
        instrument_id,
        as_of,
        quantity,
        price as price_amount_native,
        market_value as market_value_native,
        cost_basis as cost_basis_native,
        created_at
    from {{ source('raw', 'holding_snapshot') }}
),

final as (
    select * from source
)

select * from final
