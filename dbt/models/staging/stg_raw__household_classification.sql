{{ config(materialized='view') }}

-- Pass-through classification and transaction-source snapshot.

with final as (
    select
        c.transaction_id,
        c.treatment,
        c.review_state,
        c.merchant_id,
        c.identity_confirmed,
        c.provenance,
        c.rule_id,
        c.revision,
        c.source_amount,
        c.source_currency,
        c.source_ts,
        c.source_counterparty,
        c.source_kind,
        c.explanation
    from {{ source('raw', 'household_classification') }} as c
)

select * from final
