{{ config(materialized='view') }}

-- Pass-through staging view for `raw.document`.
--
-- Statements, tax forms, salary slips, invoices. Hashed by
-- `sha256` for idempotent ingestion. `account_id` is nullable —
-- documents may attach only to an entity (e.g. annual tax letters).

with final as (
    select
        d.id as document_id,
        d.entity_id,
        d.account_id,
        d.kind,
        d.issued_at,
        d.title,
        d.storage_uri,
        d.sha256,
        d.bytes,
        d.mime,
        d.created_at
    from {{ source('raw', 'document') }} as d
)

select * from final
