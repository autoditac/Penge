-- Asserts the documented grain of `mart_cashflow_daily`:
-- exactly one row per (account_id, as_of). A regression in the
-- aggregation that introduced row duplication would silently
-- double-count cashflows; this test catches that.

select
    account_id,
    as_of,
    count(*) as row_count
from {{ ref('mart_cashflow_daily') }}
group by account_id, as_of
having count(*) > 1
