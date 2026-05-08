{{ config(materialized='view') }}

-- Pass-through staging view for `raw.entity`.
--
-- Renames the surrogate primary key to `entity_id` so downstream
-- joins read naturally. No business logic — see ADR-0008 for the
-- canonical schema.

with source as (
    select
        id as entity_id,
        name,
        kind,
        created_at,
        updated_at
    from {{ source('raw', 'entity') }}
),

final as (
    select * from source
)

select * from final
