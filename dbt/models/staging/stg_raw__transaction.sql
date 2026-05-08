{{ config(materialized='view') }}

-- Pass-through staging view for `raw.transaction` (all providers).
--
-- This is the multi-source canonical staging model; provider-specific
-- slices (e.g. `stg_nordnet__transactions`) join through `raw.account`
-- and pre-filter. Money columns are renamed with explicit currency
-- suffixes (`_amount_native`) to make the FX boundary obvious in
-- downstream marts.

with source as (
    select
        id as transaction_id,
        account_id,
        instrument_id,
        ts,
        value_date,
        kind,
        quantity,
        price as price_amount_native,
        amount as amount_native,
        fee as fee_amount_native,
        tax as tax_amount_native,
        fx_rate,
        counterparty,
        description,
        external_id,
        raw,
        created_at
    from {{ source('raw', 'transaction') }}
),

final as (
    select * from source
)

select * from final
