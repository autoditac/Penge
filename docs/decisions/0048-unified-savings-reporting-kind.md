# 0048 — Unify cash savings in reporting while preserving source kinds

- **Status:** Proposed
- **Date:** 2026-10-01
- **Deciders:** @autoditac
- **Tags:** reporting, web

## Context and Problem Statement

The canonical `account.kind` vocabulary carries connector and audit meaning.
Nordnet uses `opsparingskonto` for its cash savings account (ADR-0008), while
a bank account can be explicitly classified as `savings` (issue #325).
Treating both source values as different reporting categories split one
household asset class across current allocation, historical performance, and
liquidity reporting.

## Decision Drivers

- Group economically equivalent cash savings together in every kind-based report.
- Preserve the original `account.kind` for source details, connector behavior,
  and auditability.
- Keep the category mapping in one server-side definition and make it explicit
  in the typed API consumed by the WebUI.
- Leave entity, currency, and all unrelated kind groupings unchanged.

## Considered Options

1. **Normalize source account kinds** — change Nordnet's canonical
   `opsparingskonto` to `savings`.
2. **Normalize independently in each report/client** — duplicate source-kind
   aliases in API, WebUI, and future consumers.
3. **Expose a derived reporting kind** — retain source kinds and provide one
   server-defined grouping category to all reporting surfaces.

## Decision

We chose **Option 3**. `account.kind` remains the canonical source value;
`reporting_kind` maps `opsparingskonto` to `savings` and leaves every other
kind unchanged. `/allocation/current?by=kind` groups and computes EUR/DKK sums
and EUR weights using this category. `/accounts` returns both the original
`kind` and derived `reporting_kind`, allowing historical WebUI series, weights,
drift, drill-down, and liquid share to use the same category without replacing
source detail.

## Consequences

### Positive

- Cash savings appear as one category in current and historical reporting.
- Source-specific account semantics remain available unchanged.
- The API owns the mapping, so clients consume a reporting category instead
  of maintaining source aliases.

### Negative

- Account summaries carry both source and reporting kinds, which consumers
  must distinguish.
- New source kinds that need grouped reporting require an explicit mapping and
  regression coverage.

### Neutral

- Allocation by entity or currency is unchanged.
- This reporting classification does not change tax treatment, ingestion, or
  stored account data.

## Alternatives in detail

### Option 1 — normalize source account kinds

Rejected because replacing `opsparingskonto` would discard the connector's
canonical source vocabulary and weaken audit semantics locked in by ADR-0008.

### Option 2 — normalize independently per report

Rejected because duplicated aliases could drift between API allocations,
historical series, and additional clients.

## Links

- [ADR-0008 — Nordnet account modelling](0008-nordnet-account-modelling.md)
- [ADR-0047 — Per-account bank metadata corrections](0047-per-account-bank-metadata-corrections.md)
- [Read API](../api/index.md)
- [Modern WebUI](../web/modern-webui.md)
- Issue #325 — Bank account metadata corrections
- Issue #326 — Unify savings reporting
