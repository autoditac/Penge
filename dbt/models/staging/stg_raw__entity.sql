{{ config(materialized='view') }}

-- Pass-through staging view for `raw.entity`.
--
-- Renames the surrogate primary key to `entity_id` so downstream
-- joins read naturally. No business logic — see ADR-0008 for the
-- canonical schema.

with final as (
    select
        e.id as entity_id,
        e.name,
        e.kind,
        e.created_at,
        e.updated_at
    from {{ source('raw', 'entity') }} as e
)

select * from final
