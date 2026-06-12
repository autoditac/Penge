-- Asserts the documented grain of `mart_position_value_daily`:
-- exactly one row per (account_id, instrument_id, as_of). Duplicated
-- panel rows would silently double-count balances and distort every
-- downstream return factor.

select
    account_id,
    instrument_id,
    as_of,
    count(*) as row_count
from {{ ref('mart_position_value_daily') }}
group by account_id, instrument_id, as_of
having count(*) > 1
