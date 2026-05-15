# 0031 — HouseholdPlan: end-to-end projection orchestrator

- **Status:** Accepted
- **Date:** 2026-05-15
- **Deciders:** @autoditac
- **Tags:** sim

## Context and Problem Statement

All individual sim modules (cashflow, liquid, bridge, payout, folkepension, spending, tax)
existed as independent units. To produce a complete FIRE projection for a DK/DE household
a caller had to wire them together manually — knowing the correct call order, handling
currency conversion, propagating the pension balance forward, and collecting warnings.
This wiring logic was duplicated across tests and notebooks, and there was no single
canonical entry point for "run the full household projection".

## Decision Drivers

- Single, auditable entry point for full-household projections
- Keep each sub-module independently testable (no circular coupling)
- Immutable result types so projections can be compared and diffed safely
- Graceful degradation: missing liquid accounts or payout configs produce warnings, not panics

## Considered Options

1. **`HouseholdPlan` + `project_household()` in `penge.sim.plan`** — a top-level frozen
   Pydantic config + a pure orchestrator function in a new module.
2. **`HouseholdPlan` as a method on `CashflowProjection`** — tightly couple the
   orchestrator to the cashflow module.
3. **Notebook-level glue code only** — no library abstraction, each analysis wires modules
   ad hoc.

## Decision

We chose **Option 1**, because:

- A dedicated `plan.py` module keeps the orchestration concern separate from each
  sub-module's own logic; `cashflow.py` does not need to know about liquid accounts.
- `CashflowProjection.payout_at()` already provides a clean seam to inject the
  end-of-accumulation pension balance; the orchestrator uses it without duplicating
  payout math.
- Frozen Pydantic models (`HouseholdPlan`, `HouseholdProjectionResult`) give the same
  immutability guarantees used throughout the sim layer.
- Warnings-as-list (not exceptions) for skippable sub-steps matches the pattern used
  in `payout.py` and keeps partial results usable.

## Consequences

### Positive

- One importable function (`project_household`) produces a complete, audited projection.
- Phase classification (ACCUMULATION / BRIDGE / RETIREMENT) is centralised and testable.
- `HouseholdProjectionResult` carries the full `ProjectionAuditRecord` so every run is
  traceable to the exact assumption versions used.

### Negative

- Callers must supply all sub-configs (cashflow, liquid, bridge, payout, folkepension,
  spending, tax) even when only a subset is needed; optional templates mitigate this.
- `FolkepensionResult` is a frozen dataclass (not Pydantic), so `HouseholdProjectionResult`
  requires `arbitrary_types_allowed=True`.

### Neutral

- `project_household` is a pure function with no side effects; caching or parallelism can
  be added later without API changes.

## Links

- Closes #167
- `src/penge/sim/plan.py`
- `tests/sim/test_plan.py`
- ADR-0028 (payout model), ADR-0029 (folkepension), ADR-0030 (contribution routing)
