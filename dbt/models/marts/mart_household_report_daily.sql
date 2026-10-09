{{ config(materialized='table') }}

-- Daily signed allocation totals. Category splits are retained at leaf
-- category grain; parent rollups are calculated by consumers without adding
-- parent values into household totals.

with eligible as (
    select
        f.entity_id,
        f.account_id,
        f.account_kind,
        f.account_currency,
        f.as_of,
        f.treatment,
        f.category_id,
        f.transaction_id,
        f.allocation_amount_native,
        f.allocation_amount_eur,
        f.allocation_amount_dkk,
        f.is_default_scope,
        f.classification_review_state,
        f.classification_source_current,
        f.source_snapshot_drift,
        f.allocation_mismatch,
        case
            when f.treatment = 'unclassified' and f.allocation_amount_native > 0
                then 'income'
            when f.treatment = 'unclassified' and f.allocation_amount_native < 0
                then 'expense'
            else f.treatment
        end as reporting_treatment
    from {{ ref('fct_household_report_allocation') }} as f
    where
        f.treatment in ('income', 'expense', 'refund', 'unclassified')
        and (
            f.treatment != 'unclassified'
            or f.allocation_amount_native != 0
        )
),

aggregated as (
    select
        e.entity_id,
        e.account_id,
        e.account_kind,
        e.account_currency,
        e.as_of,
        e.treatment,
        e.reporting_treatment,
        e.category_id,
        e.is_default_scope,
        sum(e.allocation_amount_native)::numeric(20, 4)
            as allocation_amount_native,
        coalesce(sum(e.allocation_amount_eur), 0::numeric)
            as known_allocation_amount_eur,
        coalesce(sum(e.allocation_amount_dkk), 0::numeric)
            as known_allocation_amount_dkk,
        count(*) filter (where e.allocation_amount_eur is null)
            as missing_fx_count_eur,
        count(*) filter (where e.allocation_amount_dkk is null)
            as missing_fx_count_dkk,
        count(distinct e.transaction_id) as transaction_count,
        count(distinct e.transaction_id) filter (
            where e.treatment = 'unclassified'
        ) as unclassified_transaction_count,
        count(distinct e.transaction_id) filter (
            where e.treatment = 'unclassified'
            and e.allocation_amount_native < 0
        ) as unclassified_expense_count,
        count(distinct e.transaction_id) filter (
            where e.classification_review_state = 'needs_review'
            or not e.classification_source_current
        ) as classification_review_count,
        count(distinct e.transaction_id) filter (
            where e.source_snapshot_drift
        ) as source_snapshot_drift_count,
        count(distinct e.transaction_id) filter (
            where e.allocation_mismatch
        ) as allocation_mismatch_count
    from eligible as e
    group by
        e.entity_id,
        e.account_id,
        e.account_kind,
        e.account_currency,
        e.as_of,
        e.treatment,
        e.reporting_treatment,
        e.category_id,
        e.is_default_scope
),

final as (
    select
        a.entity_id,
        a.account_id,
        a.account_kind,
        a.account_currency,
        a.as_of,
        a.treatment,
        a.reporting_treatment,
        a.category_id,
        a.is_default_scope,
        a.allocation_amount_native,
        case
            when a.missing_fx_count_eur = 0 then a.known_allocation_amount_eur
        end::numeric(20, 4) as allocation_amount_eur,
        a.known_allocation_amount_eur::numeric(24, 8)
            as allocation_known_amount_eur,
        a.missing_fx_count_eur,
        case
            when a.missing_fx_count_dkk = 0 then a.known_allocation_amount_dkk
        end::numeric(20, 4) as allocation_amount_dkk,
        a.known_allocation_amount_dkk::numeric(24, 8)
            as allocation_known_amount_dkk,
        a.missing_fx_count_dkk,
        a.transaction_count,
        a.unclassified_transaction_count,
        a.unclassified_expense_count,
        a.classification_review_count,
        a.source_snapshot_drift_count,
        a.allocation_mismatch_count
    from aggregated as a
)

select * from final
