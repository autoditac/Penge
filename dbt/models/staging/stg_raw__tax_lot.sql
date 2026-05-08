{{ config(materialized='view') }}

-- Pass-through staging view for `raw.tax_lot`.
--
-- Per-lot accounting tying open and close transactions. Open lots
-- have `close_transaction_id` / `closed_at` / `proceeds` /
-- `realized_gain` null. The `method` column records the lot-matching
-- method (e.g. `gennemsnitsmetoden`, `fifo`) so reports can verify
-- the correct regime was applied.

with final as (
    select
        l.id as tax_lot_id,
        l.account_id,
        l.instrument_id,
        l.open_transaction_id,
        l.close_transaction_id,
        l.opened_at,
        l.closed_at,
        l.quantity,
        l.cost_basis as cost_basis_amount_native,
        l.proceeds as proceeds_amount_native,
        l.realized_gain as realized_gain_amount_native,
        l.method,
        l.created_at,
        l.updated_at
    from {{ source('raw', 'tax_lot') }} as l
)

select * from final
