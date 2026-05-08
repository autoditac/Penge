{{ config(materialized='view') }}

-- Pass-through staging view for `raw.document`.
--
-- Statements, tax forms, salary slips, invoices. Hashed by
-- `sha256` for idempotent ingestion. `account_id` is nullable —
-- documents may attach only to an entity (e.g. annual tax letters).

with source as (
    select
        id as document_id,
        entity_id,
        account_id,
        kind,
        issued_at,
        title,
        storage_uri,
        sha256,
        bytes,
        mime,
        created_at
    from {{ source('raw', 'document') }}
),

final as (
    select * from source
)

select * from final
