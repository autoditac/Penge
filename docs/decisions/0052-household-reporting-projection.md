# 0052 — Household income and expense reporting projection

- **Status:** Proposed
- **Date:** 2026-10-03
- **Deciders:** @autoditac
- **Tags:** data-model, dbt, api, web, mcp

## Context and Problem Statement

Household reports need to classify and reconcile account movements without
changing the existing raw cashflow, net-worth, tax, or investment-return
semantics. Category splits, explicit transfer/refund treatment, and PayPal
payment details add new reporting concepts; treating these as edits to
`mart_cashflow_daily` would silently change existing consumers and could count
the same purchase twice.

## Decision Drivers

- A bank transaction is the sole financial fact for household income and
  expense totals.
- Category splits and provider detail must reconcile to exact signed bank
  amounts and remain auditable.
- Missing exchange rates and incomplete history must remain visible.
- Existing marts and tax inputs must retain their current meaning.
- API and MCP consumers need deterministic, typed read contracts.

## Considered Options

1. **Replace existing cashflow semantics** — add categories and PayPal detail
   directly to `mart_cashflow_daily`.
2. **Create an isolated household reporting projection** — consume the
   categorization and detail-link contracts while leaving existing marts
   unchanged.
3. **Aggregate PayPal source rows independently** — join a second provider
   ledger into expense totals.

## Decision

We chose **Option 2**. A separate household dbt fact and reporting mart derive
economic totals from canonical bank transactions, classification treatment,
and signed bank-currency allocations. API reads use this projection through
the existing typed FastAPI/OpenAPI boundary. A read-only MCP tool may expose
aggregated report values only.

Payment-provider detail is enrichment, not a cashflow source. A detail link is
usable for reconciliation or display only while its explicit allocation sums
exactly to the signed bank movement and its recorded source revision and bank
source snapshot remain current. No amount/date-only match is treated as proof.
Unknown PayPal event kinds remain unknown; generic debit/credit direction does
not establish purchase, funding, or refund semantics.

Expense allocations are stored signed like the bank movement and reported as
positive gross expense magnitudes. Refund allocations are positive, belong to
an expense category, and reduce that category's net expense on the bank
refund's own value date. Transfers and explicitly excluded movements do not
become income or expense. Unclassified bank movements use a signed-polarity
fallback: positive credits contribute to headline income and negative debits
to gross expenses. They remain `treatment='unclassified'` review items with no
category allocation or learning evidence. The mart exposes this fallback as
`reporting_treatment`, shared by the API, mart, and MCP consumer.
This keeps headline cashflow truthful while classification is pending;
otherwise unreviewed salary credits would show zero income and an incorrect
surplus.

## Consequences

### Positive

- Existing cashflow, net-worth, returns, and tax marts keep their established
  semantics.
- Bank-only totals are immune to duplicate PayPal detail imports.
- Split and parent-category totals can be checked for exact conservation and
  non-duplicating roll-up.
- Missing FX and uncertain history are explicit rather than success-shaped
  zeroes.

### Negative

- The new projection depends on the household categorization and provider
  detail-link schemas.
- API consumers must understand separate gross expenses, refunds, and net
  expenses, and must handle unavailable currency totals.
- A dbt shadow refresh must build and promote the new marts with the existing
  guarded reporting refresh.
- An unreviewed positive transfer can temporarily inflate headline income
  until it is explicitly classified as a transfer.

### Neutral

- Parent categories intentionally repeat descendant values for drilldown;
  household totals are calculated from allocation rows only once.
- PayPal detail remains review-only when it is unmatched, ambiguous, stale, or
  not exactly reconciled.

## Alternatives in detail

### Option 1 — Change the existing cashflow mart

Rejected because `mart_cashflow_daily` is also consumed by current charts and
the investment-returns methodology. Reinterpreting it would create an
unrelated regression surface and blur the difference between account movement
and household economic expense.

### Option 3 — Sum PayPal source rows

Rejected because checking-account bookings already represent the cash
movement. A parallel PayPal sum can double-count spending, duplicate funding
legs, and turn unknown provider events into false expenses.

## Links

- [ADR-0004 — EUR and DKK shown in parallel](0004-eur-and-dkk-shown-in-parallel.md)
- [ADR-0005 — LLM access via MCP only](0005-llm-access-via-mcp-only.md)
- [ADR-0035 — FastAPI read API](0035-fastapi-read-api.md)
- [Household reporting API](../api/household-reporting.md)
- Issue [#333](https://github.com/autoditac/Penge/issues/333), epic
  [#329](https://github.com/autoditac/Penge/issues/329)
