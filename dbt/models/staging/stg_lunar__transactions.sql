{{ config(materialized='view') }}

-- Staging view for Lunar transactions.
--
-- Sourced from the Enable Banking PSD2 connector
-- (`penge.ingest.lunar`). The loader has already canonicalised kind
-- (CRDT→deposit, DBIT→withdrawal) and signed the amount, so this
-- view is a thin filter on `account.provider = 'lunar'`. Note that
-- Lunar's Aktiesparekonto subaccount is identified by
-- `account.dk_tax_treatment = 'aktiesparekonto'` rather than a
-- separate provider slug; downstream tax models filter on that
-- column.

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
    a.currency as account_currency,
    a.dk_tax_treatment
from {{ source('raw', 'transaction') }} as t
inner join {{ source('raw', 'account') }} as a on t.account_id = a.id
where a.provider = 'lunar'
