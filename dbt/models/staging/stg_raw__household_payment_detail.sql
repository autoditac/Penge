{{ config(materialized='view') }}

-- Pass-through of the detail-only provider table. Never a cashflow source.

with final as (
    select
        d.id as detail_id,
        d.provider,
        d.source_account_id,
        d.external_id as external_reference,
        d.connection_id,
        d.ts,
        d.amount as amount_native,
        d.currency,
        d.merchant_name,
        d.reference,
        d.event_kind,
        d.source_fields,
        d.revision,
        d.last_seen_at
    from {{ source('raw', 'household_payment_detail') }} as d
)

select * from final
