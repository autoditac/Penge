{{ config(materialized='view') }}

-- Pass-through staging view for `raw.account`.
--
-- Renames the surrogate primary key to `account_id` and exposes
-- canonical column names for downstream marts. No business logic —
-- see ADR-0008.

with source as (
    select
        id as account_id,
        entity_id,
        provider,
        external_id,
        name,
        kind,
        currency,
        iban,
        opened_at,
        closed_at,
        created_at,
        updated_at
    from {{ source('raw', 'account') }}
),

final as (
    select * from source
)

select * from final
