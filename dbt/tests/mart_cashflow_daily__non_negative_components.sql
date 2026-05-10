-- Inflow and outflow components are stored as non-negative magnitudes
-- (the sign lives in `net_*`). Catch any future refactor that
-- accidentally lets a negative leak through.

select
    account_id,
    as_of,
    inflow_acct_ccy,
    outflow_acct_ccy
from {{ ref('mart_cashflow_daily') }}
where inflow_acct_ccy < 0 or outflow_acct_ccy < 0
