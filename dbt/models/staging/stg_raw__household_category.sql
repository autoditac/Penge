{{ config(materialized='view') }}

-- Pass-through household category hierarchy; reporting rollups are downstream.

with final as (
    select
        c.id as category_id,
        c.name,
        c.kind,
        c.parent_id,
        c.sort_order,
        c.archived,
        c.revision
    from {{ source('raw', 'household_category') }} as c
)

select * from final
