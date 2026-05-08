-- Custom test: no FX gaps in the EUR/DKK columns.
--
-- For every row in the mart with a non-null account-currency balance,
-- both `balance_eur` and `balance_dkk` must be non-null. A null here
-- means the FX forward-fill failed to find any rate at-or-before the
-- `as_of` date for the account currency or for DKK, and the time
-- series should not be published with holes.

select
    entity_id,
    account_id,
    account_currency,
    as_of,
    balance_acct_ccy,
    balance_eur,
    balance_dkk
from {{ ref('mart_net_worth_daily') }}
where
    balance_acct_ccy is not null
    and (balance_eur is null or balance_dkk is null)
