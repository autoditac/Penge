-- Asserts the documented grain of `mart_net_worth_daily`:
-- exactly one row per (account_id, as_of). A regression in the
-- forward-fill / FX joins that introduced row duplication would
-- silently double-count balances; this test catches that.

select
    account_id,
    as_of,
    count(*) as row_count
from {{ ref('mart_net_worth_daily') }}
group by account_id, as_of
having count(*) > 1
