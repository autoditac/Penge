{{ config(materialized='view') }}

-- Staging view for PFA pension transactions.
--
-- Sourced from the PFA Pensionsoversigt PDF parser
-- (`penge.ingest.pfa`). PFA does not break out individual
-- transfers on the consumer statement, so the loader posts one
-- summary transaction per non-zero financial-summary line per
-- scheme (contribution, return, fee, PAL-skat) dated on the
-- statement's `period_to`. This view is a thin filter on
-- `account.provider = 'pfa'`.
--
-- All amounts are DKK. PFA only supports DKK on the consumer
-- statement. PAL-skat is posted as a negative `tax` transaction;
-- fees are posted as a negative `fee` transaction.

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
where a.provider = 'pfa'
