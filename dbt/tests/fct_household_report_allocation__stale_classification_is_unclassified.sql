-- A stale classification snapshot or pending review may not label report
-- amounts as confirmed income, expense, refund, transfer, or exclusion.

select
    f.transaction_id,
    f.treatment,
    f.classification_review_state,
    f.source_snapshot_drift
from {{ ref('fct_household_report_allocation') }} as f
where
    (
        f.source_snapshot_drift
        or f.classification_review_state = 'needs_review'
        or not f.classification_source_current
    )
    and f.treatment != 'unclassified'
