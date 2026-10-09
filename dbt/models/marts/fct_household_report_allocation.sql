{{ config(materialized='table') }}

-- One row per bank allocation, plus a synthetic line for treatments that do
-- not have category allocations. Provider detail is intentionally not joined.

with bank_transactions as (
    select
        t.transaction_id,
        t.account_id,
        a.entity_id,
        a.kind as account_kind,
        a.currency as account_currency,
        t.ts,
        t.created_at as transaction_created_at,
        t.net_amount_native as source_amount_native,
        t.counterparty,
        t.description,
        c.treatment as stored_treatment,
        c.review_state as classification_review_state,
        c.revision as classification_revision,
        c.merchant_id,
        coalesce(t.value_date, (t.ts at time zone 'UTC')::date) as as_of,
        c.transaction_id is not null as has_classification,
        (
            c.transaction_id is not null
            and c.source_amount is not distinct from t.net_amount_native
            and c.source_currency is not distinct from a.currency
            and c.source_ts is not distinct from t.ts
            and c.source_counterparty is not distinct from t.counterparty
            and c.source_kind is not distinct from t.kind
        ) as source_snapshot_matches,
        (
            c.transaction_id is not null
            and c.review_state in ('classified', 'unclassified')
            and c.source_amount is not distinct from t.net_amount_native
            and c.source_currency is not distinct from a.currency
            and c.source_ts is not distinct from t.ts
            and c.source_counterparty is not distinct from t.counterparty
            and c.source_kind is not distinct from t.kind
        ) as classification_source_current
    from {{ ref('stg_raw__transaction') }} as t
    inner join {{ ref('stg_raw__account') }} as a on t.account_id = a.account_id
    left join {{ ref('stg_raw__household_classification') }} as c
        on t.transaction_id = c.transaction_id
),

allocation_totals as (
    select
        a.transaction_id,
        count(*) as allocation_count,
        sum(a.amount_native) as allocation_amount_native
    from {{ ref('stg_raw__household_allocation') }} as a
    group by a.transaction_id
),

classified_transactions as (
    select
        b.*,
        b.has_classification and not b.source_snapshot_matches
            as source_snapshot_drift,
        coalesce(totals.allocation_count, 0) as allocation_count,
        coalesce(totals.allocation_amount_native, 0::numeric)
            as allocation_amount_native,
        case
            when
                b.classification_source_current
                and (
                    (
                        b.classification_review_state = 'classified'
                        and b.stored_treatment in (
                            'expense',
                            'income',
                            'refund',
                            'transfer',
                            'excluded'
                        )
                    )
                    or (
                        b.classification_review_state = 'unclassified'
                        and b.stored_treatment = 'unclassified'
                    )
                )
                then b.stored_treatment
            else 'unclassified'
        end as effective_treatment,
        case
            when
                b.classification_source_current
                and b.classification_review_state = 'classified'
                and b.stored_treatment in ('expense', 'income', 'refund')
                then (
                    coalesce(totals.allocation_amount_native, 0::numeric)
                    is distinct from b.source_amount_native
                )
            else false
        end as allocation_mismatch
    from bank_transactions as b
    left join allocation_totals as totals
        on b.transaction_id = totals.transaction_id
),

allocation_rows as (
    select
        c.transaction_id,
        c.account_id,
        c.entity_id,
        c.account_kind,
        c.account_currency,
        c.as_of,
        c.transaction_created_at,
        c.source_amount_native,
        a.amount_native,
        c.effective_treatment as treatment,
        a.category_id,
        cat.name as category_name,
        cat.kind as category_kind,
        cat.parent_id as category_parent_id,
        c.counterparty,
        c.description,
        c.merchant_id,
        c.classification_source_current,
        c.source_snapshot_drift,
        c.classification_review_state,
        c.classification_revision,
        c.allocation_mismatch
    from classified_transactions as c
    inner join {{ ref('stg_raw__household_allocation') }} as a
        on c.transaction_id = a.transaction_id
    inner join {{ ref('stg_raw__household_category') }} as cat
        on a.category_id = cat.category_id
    where
        c.classification_source_current
        and c.effective_treatment in ('expense', 'income', 'refund')
        and c.allocation_count > 0
        and not c.allocation_mismatch

    union all

    select
        c.transaction_id,
        c.account_id,
        c.entity_id,
        c.account_kind,
        c.account_currency,
        c.as_of,
        c.transaction_created_at,
        c.source_amount_native,
        c.source_amount_native as amount_native,
        case
            when
                c.classification_source_current
                and c.effective_treatment in (
                    'transfer', 'excluded', 'unclassified'
                )
                then c.effective_treatment
            else 'unclassified'
        end as treatment,
        null::uuid as category_id,
        null::text as category_name,
        null::text as category_kind,
        null::uuid as category_parent_id,
        c.counterparty,
        c.description,
        case when c.classification_source_current then c.merchant_id end
            as merchant_id,
        c.classification_source_current,
        c.source_snapshot_drift,
        c.classification_review_state,
        c.classification_revision,
        c.allocation_mismatch
    from classified_transactions as c
    where not (
        c.classification_source_current
        and c.effective_treatment in ('expense', 'income', 'refund')
        and c.allocation_count > 0
        and not c.allocation_mismatch
    )
),

with_rates as (
    select
        a.*,
        case
            when a.account_currency = 'EUR' then 1::numeric(20, 8)
            else (
                select fx.rate
                from {{ ref('stg_raw__fx_rate') }} as fx
                where
                    fx.base_ccy = 'EUR'
                    and fx.quote_ccy = a.account_currency
                    and fx.as_of <= a.as_of
                order by fx.as_of desc
                limit 1
            )
        end as eur_to_account_rate,
        (
            select fx.rate
            from {{ ref('stg_raw__fx_rate') }} as fx
            where
                fx.base_ccy = 'EUR'
                and fx.quote_ccy = 'DKK'
                and fx.as_of <= a.as_of
            order by fx.as_of desc
            limit 1
        ) as eur_to_dkk_rate
    from allocation_rows as a
),

converted as (
    select
        r.*,
        case
            when r.account_currency = 'EUR' then r.amount_native
            else r.amount_native / nullif(r.eur_to_account_rate, 0)
        end as amount_eur,
        case
            when r.account_currency = 'DKK' then r.amount_native
            when
                r.account_currency = 'EUR'
                then r.amount_native * r.eur_to_dkk_rate
            else
                r.amount_native
                / nullif(r.eur_to_account_rate, 0)
                * r.eur_to_dkk_rate
        end as amount_dkk
    from with_rates as r
),

final as (
    select
        c.transaction_id,
        c.account_id,
        c.entity_id,
        c.account_kind,
        c.account_currency,
        c.as_of,
        c.transaction_created_at,
        c.source_amount_native,
        c.amount_native as allocation_amount_native,
        c.treatment,
        c.category_id,
        c.category_name,
        c.category_kind,
        c.category_parent_id,
        c.counterparty,
        c.description,
        c.merchant_id,
        c.classification_source_current,
        c.source_snapshot_drift,
        c.classification_review_state,
        c.classification_revision,
        c.allocation_mismatch,
        c.amount_eur as allocation_amount_eur,
        c.amount_dkk as allocation_amount_dkk,
        (c.account_kind = 'checking') as is_default_scope
    from converted as c
)

select * from final
