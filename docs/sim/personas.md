# Simulation personas

This page describes the user personas behind the delivered simulation and tax features.
It is written as product context, not as implementation detail or backlog scope.
Use it together with the [simulation user stories](user-stories.md) when designing dashboards, scenario presets, MCP tools, or new simulation APIs.

## Primary persona: DK/DE FIRE household planner

### Summary

The primary user is a technically comfortable DK/DE household planning long-term financial independence, early retirement, and retirement cashflow.
The household spans Denmark and Germany, holds assets in EUR and DKK, and needs trustworthy projections that combine salary, pension, liquid investing, tax treatment, public pension effects, and bridge withdrawals.

This persona does not want a generic personal-finance dashboard.
They want an auditable planning system that can answer concrete household decisions with reproducible numbers.

### Situation

- Household finances cross country boundaries: Danish tax rules, German context, EUR and DKK accounts, and Danish pension products all matter.
- The household saves monthly and expects cash to move across account types over time.
- Some assets are tax-advantaged, such as Aktiesparekonto (ASK), while others sit in ordinary brokerage accounts (*frie midler*).
- The household may retire before public and occupational pension income starts, creating a bridge phase funded by liquid assets.
- Retirement income may be high enough to trigger Topskat and reduce Folkepension pensionstillæg.
- The user is willing to work with precise assumptions, but needs the system to make tax and modelling boundaries explicit.

### Goals

- Decide whether the household is on track for financial independence.
- Compare major choices such as reduced work, different savings rates, property decisions, or retirement timing.
- Understand how monthly savings should be allocated between ASK and frie midler once the ASK cap is reached.
- Compare investment choices by tax treatment, ÅOP, FX conversion cost, dividend yield, and net projected outcome.
- Estimate the safe bridge withdrawal from liquid assets until pension income begins.
- Convert projected pension wealth into monthly retirement income and lump sums.
- See whether projected retirement income triggers Topskat or Folkepension modregning.
- Preserve enough auditability to trust the result later, especially for tax-sensitive decisions.

### Needs

#### Correct account routing

The persona needs contribution routing that reflects real-world constraints.
ASK must be filled only until the cumulative SKAT deposit cap is exhausted.
Overflow must move to frie midler instead of being dropped, over-counted, or silently kept in ASK.

#### Tax-aware liquid investing

The persona needs account projections that keep tax regimes separate.
ASK, Lagerbeskatning instruments, and Realisationsbeskatning instruments must not be collapsed into one generic return stream.
Dividend distributions must be modelled where they create taxable income.

#### Bridge-phase realism

The persona needs liquid assets modelled as spendable bridge capital, not only as accumulation balances.
Monthly withdrawals, realised gains, progressive aktieindkomst tax, cost basis, and dividend tax all affect whether the depot lasts.

#### Pension-income translation

The persona needs occupational pension balances translated into understandable income streams.
Livrente, Ratepension, and Aldersforsikring have different payout patterns and must be visible separately.

#### Danish retirement-tax visibility

The persona needs warnings and estimates for Danish retirement-specific effects.
Topskat exposure and Folkepension reduction are planning constraints, not afterthoughts.

#### Scenario comparison

The persona needs labelled scenarios that can be compared side by side.
The system should show which assumption changed and how the outcome moved, instead of forcing the user to compare raw model outputs manually.

#### Reproducibility and auditability

The persona needs deterministic, versioned, documented calculations.
When a projection changes, the user must be able to understand whether the change came from inputs, tax constants, market assumptions, or model logic.

### Requirements

#### Functional requirements

- The system must support EUR and DKK as first-class currencies.
- The system must preserve account identity and tax treatment through the projection.
- The system must model ASK cap usage and overflow routing.
- The system must support liquid depot accumulation and bridge decumulation.
- The system must distinguish Lagerbeskatning from Realisationsbeskatning.
- The system must support distributing and accumulating realisation funds.
- The system must model pension payout products separately.
- The system must expose Danish Topskat and Folkepension effects from projected pension income.
- The system must support scenario comparison across labelled configurations.

#### Data requirements

- Inputs must be explicit and synthetic in tests.
- Real financial documents, account numbers, real counterparties, salary numbers, and statements must not be committed.
- Tax rates, thresholds, cap values, and pension assumptions must be centralized or linked to decision records.
- FX assumptions must be visible; no hidden base-currency conversion is acceptable.

#### UX requirements

- Outputs should answer household questions directly.
- The user should see both high-level outcomes and the assumptions that produced them.
- The system should make overflow, tax drag, depletion, and pension-income effects visible as named lines.
- Scenarios should be labelled with human-readable names.
- Warnings should be actionable, such as suggesting timing, product mix, or contribution changes.

#### Engineering requirements

- Calculations must be deterministic unless explicitly sampling return paths.
- Sampling must be reproducible with seeds and documented assumptions.
- Models should be pure where possible and avoid hidden mutable state.
- Public APIs should use typed, validated configuration objects.
- Tests must cover tax-sensitive edge cases, boundary conditions, and parity cases.
- Architectural or tax-rule changes require decision records.

### Conditions

#### Country and tax context

- The household uses Danish tax rules for ASK, aktieindkomst, PAL-skat, Topskat, and Folkepension.
- German context exists in the household finances, but the delivered feature set is currently strongest on the Danish simulation path.
- Tax constants are projection aids and must be updated when law or published thresholds change.

#### Currency context

- EUR and DKK are both meaningful and must be shown or handled explicitly.
- The persona may hold EUR-denominated instruments bought from DKK cash.
- FX conversion cost can materially affect net outcomes and must be modelled where relevant.

#### Investment context

- The household may use ASK, frie midler, pension accounts, ETFs, distributing funds, and accumulating funds.
- Lager and realisation taxation both matter.
- Dividend yield is not just a return assumption; for distributing funds it creates taxable income timing.

#### Lifecycle context

- The household is modelling accumulation, early-retirement bridge years, and later pension income.
- The correct answer may change by phase.
- During bridge years, tax is effectively paid from the depot because external employment income may no longer exist.

### Restrictions

#### Product restrictions

- The platform is not an automated trading, rebalancing, or tax-filing system.
- It should support planning and auditability, not execute financial decisions.
- It should avoid presenting projections as guarantees.
- It should not hide material modelling simplifications behind a polished UI.

#### Privacy restrictions

- Raw financial documents and sensitive household data must stay out of source control.
- Tests and examples must use synthetic or anonymized data.
- Any LLM-facing path must respect the repository's MCP-only rule for private data access.

#### Modelling restrictions

- No single hidden base currency may be assumed.
- No tax rule, FX source, ASK cap, or asset-class definition may be silently changed.
- Realisation taxation must keep cost basis and taxable gains explicit.
- Public pension and tax estimates must state their scope and must not pretend to be a full tax return.

#### Workflow restrictions

- User-visible features should be traceable to user stories, tests, and documentation.
- Code changes must pass quality gates before merge.
- Review comments must be resolved before merging.
- Significant modelling or architectural decisions must be captured in ADRs.

## Secondary persona: future maintainer and reviewer

### Summary

The future maintainer is the engineer who must understand why a model exists, what household question it answers, and what would break if they changed it.
This persona may be the same human later, a reviewer, or an automation agent working under repository rules.

### Needs

- Clear links from user stories to implementation and ADRs.
- Small, explicit models with typed inputs and outputs.
- Tests that encode business meaning, not only mechanics.
- Documentation that explains modelling boundaries and tax assumptions.
- A backlog that remains clean, without retroactively stuffing every documentation insight into issues.

### Requirements

- Every new user-visible simulation feature should map to a household story.
- Every tax-sensitive change should include regression tests for edge cases.
- Every architectural change should have an ADR.
- Every PR should make its user-visible impact understandable from the description and docs.

### Restrictions

- The maintainer must not trade correctness for speed.
- The maintainer must not weaken types, swallow validation errors, or add silent fallbacks.
- The maintainer must not use real financial data as fixtures.
- The maintainer must not merge before CI, review, and review-thread resolution are complete.

## Design implications

- Prefer scenario presets that speak in household language: "ASK fills in month 6", "bridge lasts until Folkepension age", or "Topskat exposure after Ratepension starts".
- Prefer output tables that separate account, tax regime, contribution, return, tax, withdrawal, and closing balance.
- Prefer warnings that explain the planning consequence and the assumption that triggered it.
- Prefer docs and MCP responses that cite the relevant ADR or tax page when answering model questions.
- Avoid dashboards that only expose raw model classes; each surface should answer a persona need directly.
