# Household income and expense reports

Household reports are a separate projection over canonical bank transactions,
the audited categorization contract, and explicitly approved provider-detail
links.
They do not redefine `mart_cashflow_daily`, net-worth, returns, or tax marts.
See [ADR-0052](../decisions/0052-household-reporting-projection.md).

## Financial rules

- The signed checking-account booking is the one financial fact counted.
  PayPal payment detail is never a second ledger and contributes no independent
  income or expense.
- Detail enrichment is trusted only while explicit bank/detail allocations
  equal the signed bank amount, the recorded detail revision is current, and
  the bank amount, currency, timestamp, and counterparty still match the
  classification source snapshot.
- PayPal event type remains `unknown` unless a future source-specific mapping
  is supported by observed evidence and tests. A debit, credit, or generic
  transaction code alone does not prove purchase, refund, or funding.
- Expense allocations retain the signed source amount and are displayed as
  positive gross expense values. A refund is a positive bank credit allocated
  to an expense category and reduces that category on the refund booking date.
- Explicit own-account transfers and excluded movements are neither income
  nor expense. The report's default scope is checking accounts, but transfer
  recognition considers owned accounts outside the selected report scope.
- Negative unclassified bank movements remain in expense totals and are
  separately quantified. Positive unclassified credits are not presumed to be
  income.
- A transaction split conserves the exact signed bank-currency amount.
  Selecting a category filters its allocation lines and descendants; a
  transaction with multiple selected splits is still counted once.
- A parent category displays the sum of its descendants. Parent values are
  not added again to household totals.

## Currency, dates, and completeness

API money values are lossless decimal strings. EUR and DKK are separate,
parallel values; original signed currency amounts remain available for each
transaction and allocation.
Conversions follow the existing `base_ccy = 'EUR'` ECB convention at the
booking value date, using the most recent rate on or before that date and EUR
as the bridge to DKK. A missing conversion is not treated as zero: the
currency amount is null, its known subtotal is separately identified, and an
incomplete flag and missing-FX count are returned.

Report dates use `coalesce(value_date, (ts at time zone 'UTC')::date)`, matching
the existing cashflow mart. Trend buckets are clipped to the requested date
range so partial first and last periods remain explicit. Daily, monthly, and
yearly buckets are supported.

The report returns the earliest observed bank booking date and freshness
timestamps, but does not certify that statements before or after that date are
complete. Healthy provider synchronization is not evidence of full account
history. PayPal personal-account access and useful detail availability remain
unverified until explicitly authorized by the account holder.

## Read endpoints

The same report filters are accepted and echoed by summary, category, and
transaction reads:

| Filter | Meaning |
| --- | --- |
| `since`, `until` | Inclusive bank booking date range. |
| `granularity` | `day`, `month`, or `year`; controls summary trend buckets. |
| repeated `account_id` | Restrict to selected accounts; omitted means the default checking-account scope. |
| repeated `entity_id` | Restrict to household members. |
| `category_id` | Filter allocation lines to this category and its descendants. |

`entity_id` is the API's canonical member identifier, matching the existing
read API vocabulary. The UI should retain the echoed filters when opening a
category or transaction drilldown.

| Endpoint | Purpose |
| --- | --- |
| `GET /household/reports/summary` | Current-window totals, the contiguous preceding window of equal inclusive duration, trend points, coverage, reconciliation, and freshness. |
| `GET /household/reports/categories` | Current category tree with descendant-inclusive rollups; category totals include income, gross expense, refund, net expense, and surplus currency pairs. |
| `GET /household/reports/transactions` | Stable `limit`/`offset` bank-transaction-grain drilldown, with bounded text search, signed original amount, source date, treatment, splits, and only valid explicitly approved detail links. |

Summary amounts distinguish income, gross expenses, refund reductions, net
expenses (`gross_expenses - refunds`), and surplus (`income - net_expenses`).
Each EUR/DKK leg reports a nullable complete amount, a known subtotal, and
whether conversion coverage is complete. The previous window is the same
number of inclusive calendar days immediately before the requested window.
The `change` object is current minus previous for each measure and currency.

Coverage reports the true earliest available transaction date, included
bank-transaction count, unclassified expense count and amount, excluded
transfers, missing FX, and unresolved/stale PayPal detail links. Freshness reports when the response was generated, latest observed bank
booking and import timestamps, latest FX date, and latest detail-sync timestamp
when known. The existing `/meta/freshness` endpoint separately reports the
household mart's latest date and row count.

The transaction endpoint returns a bank transaction once even when it has
multiple category splits or multiple provider details. For category-filtered
reads, it retains the full bank booking and exposes the matching split subtotal
separately. Provider detail carries its stable source reference and original
source amount/currency for audit, alongside its signed bank-currency
allocation and reconciliation state. Only explicitly linked details are
returned; stale or amount-mismatched links remain visible for review and never
affect totals.

All report endpoints are read-only. Category and allocation edits are owned
by the household categorization API, not this reporting API.

## Refresh and consumer contract

The household marts are built and tested in the guarded dbt shadow refresh
before atomic promotion, so consumers do not see a partially refreshed report.
OpenAPI response models are committed to [`openapi.json`](openapi.json), and
the WebUI generates its TypeScript types from that artifact.
MCP reads, where exposed, return report aggregates and coverage only; they do
not return transaction-level detail.
