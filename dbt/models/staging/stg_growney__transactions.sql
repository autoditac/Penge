{{ config(materialized='view') }}

-- Staging view for Growney / Sutor Bank transactions.
--
-- Sourced from the Sutor Bank Depotauszug PDF parser
-- (`penge.ingest.growney`). The loader has already canonicalised
-- the Sutor "Transaktion" column to the project-wide kind
-- vocabulary (Einzahlung→deposit, Auszahlung→withdrawal,
-- Kauf→buy, Verkauf→sell, Ausschüttung→dividend, Gebühr→fee)
-- and signed Betrag (netto) accordingly, so this view is a thin
-- filter on `account.provider = 'growney'`.

select
    t.id as transaction_id,
    t.account_id,
    t.instrument_id,
    t.ts,
    t.value_date,
    t.kind,
    t.quantity,
    t.price,
    t.amount,
    t.fee,
    t.tax,
    t.fx_rate,
    t.counterparty,
    t.description,
    t.external_id,
    a.provider,
    a.kind as account_kind,
    a.currency as account_currency
from {{ source('raw', 'transaction') }} as t
inner join {{ source('raw', 'account') }} as a on t.account_id = a.id
where a.provider = 'growney'
