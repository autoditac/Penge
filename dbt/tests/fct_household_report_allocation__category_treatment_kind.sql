-- Income allocations must use income categories; expenses and refunds must
-- use expense categories. Refund lines use their original expense category.

select
    f.transaction_id,
    f.category_id,
    f.treatment,
    f.category_kind
from {{ ref('fct_household_report_allocation') }} as f
where
    (
        f.treatment = 'income'
        and f.category_kind is distinct from 'income'
    )
    or (
        f.treatment in ('expense', 'refund')
        and f.category_kind is distinct from 'expense'
    )
