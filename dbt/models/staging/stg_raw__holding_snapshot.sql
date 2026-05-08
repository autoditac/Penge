{{ config(materialized='view') }}

-- Pass-through staging view for `raw.holding_snapshot`.
--
-- Renames the surrogate primary key to `holding_snapshot_id` and
-- normalises money columns. The unique grain
-- (`account_id`, `instrument_id`, `as_of`) is enforced upstream by
-- a Postgres unique constraint and re-asserted as a dbt test below.

with final as (
    select
        h.id as holding_snapshot_id,
        h.account_id,
        h.instrument_id,
        h.as_of,
        h.quantity,
        h.price as price_amount_native,
        h.market_value as market_value_amount_native,
        h.cost_basis as cost_basis_amount_native,
        h.created_at
    from {{ source('raw', 'holding_snapshot') }} as h
)

select * from final
