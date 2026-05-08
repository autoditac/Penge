{{ config(materialized='view') }}

-- Pass-through staging view for `raw.instrument`.
--
-- Renames the surrogate primary key to `instrument_id`. Cash is
-- modelled as a synthetic instrument with `kind = 'cash'` per
-- ADR-0008.

with final as (
    select
        i.id as instrument_id,
        i.isin,
        i.ticker,
        i.mic,
        i.name,
        i.kind,
        i.currency,
        i.created_at,
        i.updated_at
    from {{ source('raw', 'instrument') }} as i
)

select * from final
