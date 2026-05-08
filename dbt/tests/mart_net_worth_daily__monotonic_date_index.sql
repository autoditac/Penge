-- Custom test: per-account date index is monotonically increasing and gap-free.
--
-- For each `account_id`, the set of `as_of` dates between
-- `min(as_of)` and `max(as_of)` must form a contiguous daily series.
-- The mart builds rows from a `generate_series(min_d, max_d, '1 day')`
-- spine, so any gap here indicates a regression in the spine logic or
-- a missing `account` join. Returning rows = test failure.

select
    account_id,
    min(as_of) as min_as_of,
    max(as_of) as max_as_of,
    count(distinct as_of) as observed_days,
    (max(as_of) - min(as_of) + 1) as expected_days
from {{ ref('mart_net_worth_daily') }}
group by account_id
having count(distinct as_of) <> (max(as_of) - min(as_of) + 1)
