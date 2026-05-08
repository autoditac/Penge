{{ config(materialized='view') }}

-- Staging view for PFA pension holdings (Investeringsprofil).
--
-- Sourced from the PFA Pensionsoversigt PDF parser. Each
-- `Investeringsprofil` row on the statement becomes one
-- holding_snapshot row, with quantity defaulting to 1 when the
-- statement does not surface unit counts (older PFA layouts).
--
-- Tickers are synthesised from the fund display name with the
-- documented `PFA:<slug>` prefix.

select
    h.id as holding_snapshot_id,
    h.account_id,
    h.instrument_id,
    h.as_of,
    h.quantity,
    h.price,
    h.market_value,
    h.cost_basis,
    a.provider,
    a.kind as account_kind,
    a.currency as account_currency,
    i.ticker as instrument_ticker,
    i.name as instrument_name
from {{ source('raw', 'holding_snapshot') }} as h
inner join {{ source('raw', 'account') }} as a on h.account_id = a.id
inner join {{ source('raw', 'instrument') }} as i on h.instrument_id = i.id
where a.provider = 'pfa'
