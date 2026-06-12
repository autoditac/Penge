-- Asserts the documented grain of `mart_returns_daily`: exactly one
-- row per (scope, scope_key, as_of). Duplicates would double-count
-- flows and corrupt chain-linked TWR downstream.

select
    scope,
    scope_key,
    as_of,
    count(*) as row_count
from {{ ref('mart_returns_daily') }}
group by scope, scope_key, as_of
having count(*) > 1
