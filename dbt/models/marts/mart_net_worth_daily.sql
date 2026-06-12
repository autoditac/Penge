{{ config(materialized='table') }}

-- Daily net-worth time series per account, valued in account currency,
-- EUR, and DKK.
--
-- Since ADR-0039 this mart is a thin aggregation of
-- `mart_position_value_daily`, which owns the forward-filled daily
-- valuation panel and the ECB FX bridge (ADR-0008). Summing the
-- position-level values guarantees that the account balances shown
-- here always equal the sum of the positions shown elsewhere.
--
-- See issues #24 and #205, ADR-0008, and ADR-0039.
--
-- v1 scope: balance time series only. Per-transaction cashflow FX
-- attribution lives in `mart_cashflow_daily`.

select
    entity_id,
    account_id,
    account_currency,
    as_of,
    sum(mv_acct_ccy)::numeric(20, 4) as balance_acct_ccy,
    sum(mv_eur)::numeric(20, 4) as balance_eur,
    sum(mv_dkk)::numeric(20, 4) as balance_dkk
from {{ ref('mart_position_value_daily') }}
group by entity_id, account_id, account_currency, as_of
