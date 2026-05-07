{{ config(materialized='view') }}

-- Staging view for Nordnet transactions.
--
-- The raw `transaction` table is multi-source; provider lives on
-- `account.provider`. This model surfaces only Nordnet rows and
-- exposes the columns downstream marts care about. It is a thin
-- pass-through — typing, deduplication, and kind canonicalisation
-- are all the loader's responsibility (see ADR-0008).

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
where a.provider = 'nordnet'
