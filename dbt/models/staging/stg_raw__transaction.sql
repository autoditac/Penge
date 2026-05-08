{{ config(materialized='view') }}

-- Pass-through staging view for `raw.transaction` (all providers).
--
-- This is the multi-source canonical staging model; provider-specific
-- slices (e.g. `stg_nordnet__transactions`) join through `raw.account`
-- and pre-filter. Money columns are renamed with explicit currency
-- suffixes (`_amount_native`) to make the FX boundary obvious in
-- downstream marts.

with final as (
    select
        t.id as transaction_id,
        t.account_id,
        t.instrument_id,
        t.ts,
        t.value_date,
        t.kind,
        t.quantity,
        t.price as price_amount_native,
        t.amount as net_amount_native,
        t.fee as fee_amount_native,
        t.tax as tax_amount_native,
        t.fx_rate,
        t.counterparty,
        t.description,
        t.external_id,
        t.raw,
        t.created_at
    from {{ source('raw', 'transaction') }} as t
)

select * from final
