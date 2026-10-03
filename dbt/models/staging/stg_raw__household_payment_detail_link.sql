{{ config(materialized='view') }}

-- Explicit bank/detail allocations in the signed bank movement currency.

with final as (
    select
        l.transaction_id,
        l.detail_id,
        l.bank_amount,
        l.detail_revision
    from {{ source('raw', 'household_payment_detail_link') }} as l
)

select * from final
