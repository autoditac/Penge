{{ config(materialized='view') }}

-- Staging view for Skat ABIS list (Aktiebaserede
-- Investeringsselskaber) listing observations.
--
-- One row per (instrument, tax_year). `listed = true` means Skat
-- recognised the ISIN as ABIS for that year (lagerbeskatning
-- applies); `listed = false` means it explicitly fell off the
-- list. Populated by `penge-abis ingest`. See ADR-0009.

select
    l.id as listing_id,
    l.instrument_id,
    l.tax_year,
    l.listed,
    l.source_file,
    l.imported_at
from {{ source('raw', 'instrument_dk_abis_listing') }} as l
