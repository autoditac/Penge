{{ config(materialized='view') }}

-- Pass-through staging view for `raw.tax_lot`.
--
-- Per-lot accounting tying open and close transactions. Open lots
-- have `close_transaction_id` / `closed_at` / `proceeds` /
-- `realized_gain` null. The `method` column records the lot-matching
-- method (e.g. `gennemsnitsmetoden`, `fifo`) so reports can verify
-- the correct regime was applied.

with source as (
    select
        id as tax_lot_id,
        account_id,
        instrument_id,
        open_transaction_id,
        close_transaction_id,
        opened_at,
        closed_at,
        quantity,
        cost_basis as cost_basis_native,
        proceeds as proceeds_amount_native,
        realized_gain as realized_gain_amount_native,
        method,
        created_at,
        updated_at
    from {{ source('raw', 'tax_lot') }}
),

final as (
    select * from source
)

select * from final
