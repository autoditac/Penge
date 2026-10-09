-- Every bank transaction produces one or more reporting lines that conserve
-- the signed canonical bank amount. Provider detail is not an input relation.

with report_totals as (
    select
        f.transaction_id,
        count(*) as reporting_line_count,
        sum(f.allocation_amount_native) as reporting_amount_native
    from {{ ref('fct_household_report_allocation') }} as f
    group by f.transaction_id
)

select
    t.transaction_id,
    t.net_amount_native,
    coalesce(r.reporting_line_count, 0) as reporting_line_count,
    coalesce(r.reporting_amount_native, 0::numeric) as reporting_amount_native
from {{ ref('stg_raw__transaction') }} as t
left join report_totals as r on t.transaction_id = r.transaction_id
where
    coalesce(r.reporting_line_count, 0) = 0
    or r.reporting_amount_native is distinct from t.net_amount_native
