{{ config(materialized='view') }}

-- Pass-through staging view for `raw.instrument`.
--
-- Renames the surrogate primary key to `instrument_id`. Cash is
-- modelled as a synthetic instrument with `kind = 'cash'` per
-- ADR-0008.

with source as (
    select
        id as instrument_id,
        isin,
        ticker,
        mic,
        name,
        kind,
        currency,
        created_at,
        updated_at
    from {{ source('raw', 'instrument') }}
),

final as (
    select * from source
)

select * from final
