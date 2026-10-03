-- A complete daily FX aggregate has a reportable amount; an incomplete one
-- stays null while retaining its known subtotal and missing count.

select
    m.account_id,
    m.as_of,
    m.treatment,
    m.category_id,
    'EUR' as currency
from {{ ref('mart_household_report_daily') }} as m
where
    (
        m.missing_fx_count_eur = 0
        and m.allocation_amount_eur is distinct from
        m.allocation_known_amount_eur::numeric(20, 4)
    )
    or (
        m.missing_fx_count_eur > 0
        and m.allocation_amount_eur is not null
    )

union all

select
    m.account_id,
    m.as_of,
    m.treatment,
    m.category_id,
    'DKK' as currency
from {{ ref('mart_household_report_daily') }} as m
where
    (
        m.missing_fx_count_dkk = 0
        and m.allocation_amount_dkk is distinct from
        m.allocation_known_amount_dkk::numeric(20, 4)
    )
    or (
        m.missing_fx_count_dkk > 0
        and m.allocation_amount_dkk is not null
    )
