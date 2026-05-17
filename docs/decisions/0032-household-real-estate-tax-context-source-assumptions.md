# 0032 — Household real-estate, tax context, and source-backed assumptions

- **Status:** Proposed
- **Date:** 2026-05-17
- **Deciders:** @autoditac
- **Tags:** sim, tax, vault

## Context and Problem Statement

The household planner can now project liquid depots, pensions, bridge years, tax drag, and readiness findings.
The remaining advanced planning questions need three related extensions.
Housing decisions must not sit outside the FIRE projection, mixed DK/DE tax assumptions must be explicit per household member, and planning assumptions copied from documents need provenance and review status before they enter `HouseholdPlan`.

These features touch different surfaces but share the same trust boundary.
They should be deterministic, auditable, and safe to use without sending raw documents to an unsanctioned LLM path.

## Decision Drivers

- Keep `HouseholdPlan` as the single auditable planning input.
- Separate spendable liquidity from home equity.
- Make member-level DK/DE tax assumptions visible in reports.
- Keep source-document extraction rule-based and reviewable.
- Avoid adding a database migration before the vault review workflow needs persistence.

## Considered Options

1. **Extend the simulation layer with typed planning models** — add property/mortgage configs, tax-context summaries, and source-assumption suggestions as frozen Pydantic models.
2. **Model housing as another liquid account** — reuse liquid-depot balances and mark property equity as spendable.
3. **Persist extracted assumptions directly into `HouseholdPlan`** — extract OCR values and immediately overwrite planning config fields.

## Decision

We chose **Option 1**.

Property and mortgage configs live in the simulation layer and are projected by `project_household()`.
Balance-sheet rows include property value, mortgage debt, and home equity, but spendable liquidity excludes home equity unless a sale is explicitly modelled.
Member tax-country context is summarized from `HouseholdPlan.members` and `TaxConfig`, and unsupported DE features are rendered as report/risk findings.
Document-backed assumptions are extracted from parsed/OCR text into `suggested` values with source provenance and must be accepted before callers use them in a plan.

## Consequences

### Positive

- Housing scenarios can be compared alongside liquid, pension, bridge, and tax outputs.
- Liquidity runway stays conservative because home equity is not treated as cash.
- Mixed DK/DE plans expose unsupported German tax assumptions instead of silently using DK semantics.
- Source-backed assumptions retain document ID, path, extraction method, and excerpt for audit review.

### Negative

- The real-estate model is planning-grade and does not cover refinancing, variable-rate resets, tax deductibility, or rental-income taxation.
- Source-assumption extraction is rule-based and will miss values that do not match the supported text patterns.
- Accepted assumptions are not persisted by this decision; callers still decide how to apply them.

### Neutral

- The model adds no new database tables.
- Future vault or MCP tools can wrap the same models without changing the planning semantics.

## Alternatives in detail

### Extend the simulation layer with typed planning models

This keeps the existing architecture intact.
It adds deterministic model outputs without introducing a new service boundary.
It also lets tests construct synthetic documents and household plans without real financial data.

### Model housing as another liquid account

This would have reused existing balance code but would conflate home equity with spendable bridge capital.
That would make liquidity runway look safer than it is unless a sale was explicitly modelled.

### Persist extracted assumptions directly into `HouseholdPlan`

This would reduce manual work but would weaken the audit trail.
OCR and parser output can be ambiguous, so assumptions must remain suggestions until reviewed.

## Links

- Closes #185
- Closes #181
- Closes #182
- `src/penge/sim/real_estate.py`
- `src/penge/sim/household_tax_context.py`
- `src/penge/sim/source_assumptions.py`
- ADR-0005
- ADR-0024
- ADR-0031
