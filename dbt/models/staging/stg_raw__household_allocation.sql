{{ config(materialized='view') }}

-- Pass-through signed category allocations in the bank transaction currency.

with final as (
    select
        a.transaction_id,
        a.category_id,
        a.amount as amount_native
    from {{ source('raw', 'household_allocation') }} as a
)

select * from final
