{{ config(materialized='view') }}

-- Pass-through staging view for `raw.account`.
--
-- Renames the surrogate primary key to `account_id` and exposes
-- canonical column names for downstream marts. No business logic —
-- see ADR-0008.

with final as (
    select
        a.id as account_id,
        a.entity_id,
        a.provider,
        a.external_id,
        a.name,
        a.kind,
        a.currency,
        a.iban,
        a.opened_at,
        a.closed_at,
        a.created_at,
        a.updated_at
    from {{ source('raw', 'account') }} as a
)

select * from final
