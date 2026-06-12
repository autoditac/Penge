-- Return factors are growth factors and must be strictly positive
-- whenever they are defined (a NULL factor means "no capital at risk
-- that day"). A zero or negative factor would mean a value series
-- went negative, which the position panel cannot produce — so any
-- such row indicates a flow-handling bug.

select
    scope,
    scope_key,
    as_of,
    return_factor_eur,
    return_factor_dkk
from {{ ref('mart_returns_daily') }}
where
    coalesce(return_factor_eur, 1) <= 0
    or coalesce(return_factor_dkk, 1) <= 0
