# Simulation user stories

This page records the user-visible stories that motivated the delivered simulation and tax features.
It is not a backlog.
It is a product map: each story describes a household question Penge can now answer.
Where an ADR or documentation page exists for the underlying implementation, a link is included; stories that share the same technical foundation may reference the same record.

## Household FIRE projection

### Story: See whether we are on track

As a DK/DE household planning for financial independence, I want to project salary, savings, pension accrual, taxes, and inflation over time, so that I can see whether our projected assets cover our target spending.

Penge supports this with deterministic cashflow projections, time-bounded income and contribution rules, opening pension balances, PAL-skat on pension growth, and historical bootstrap return paths.
The architectural rationale is captured in [ADR-0010](../decisions/0010-sim-return-model.md), [ADR-0011](../decisions/0011-sim-cashflow-engine.md), [ADR-0012](../decisions/0012-sim-goal-model.md), and [ADR-0014](../decisions/0014-sim-montecarlo-runner.md).

### Story: Compare life choices side by side

As a household making decisions such as reduced working hours, buying property, or changing savings rates, I want to compare labelled scenarios side by side, so that I can see the effect on FIRE timing and terminal balances.

Penge supports this through scenario comparison and scenario-diff simulation.
The scenario architecture is documented in [ADR-0015](../decisions/0015-sim-scenario-engine.md).

## Liquid investing during accumulation

### Story: Split money between ASK and frie midler correctly

As a saver who still has room in an Aktiesparekonto (ASK), I want monthly contributions to fill ASK first and then overflow to frie midler once the SKAT deposit cap is exhausted, so that the projection follows the real contribution constraint.

Penge supports this with the contribution router documented in [ADR-0030](../decisions/0030-sim-contribution-routing.md).
It can show the year-level split and the exact month where the cap is reached.

### Story: Model ASK and normal depot taxes separately

As a household with both ASK and normal brokerage accounts, I want each account projected with its own tax regime, so that ASK's 17% Lager tax is not mixed with frie midler taxation.

Penge supports this through the liquid depot simulation model documented in [ADR-0027](../decisions/0027-liquid-depot-simulation-model.md).
ASK accounts are modelled separately from frie midler, with account-specific tax treatment and contribution-cap tracking.

### Story: Choose between Lagerbeskatning and Realisationsbeskatning

As an investor comparing Danish ETF and fund choices, I want to see the difference between Lagerbeskatning and Realisationsbeskatning, so that the projection reflects when tax is paid and how compounding changes.

Penge supports this in the liquid depot model documented in [ADR-0027](../decisions/0027-liquid-depot-simulation-model.md).
Lager funds tax annual mark-to-market gains, while realisation funds defer capital-gain taxation until sale and can separately model dividend distributions.

### Story: Compare fund cost and tax drag

As an investor choosing between instruments, I want to compare ÅOP, tax regime, return assumptions, and FX conversion costs together, so that I can evaluate the net result rather than a single headline fee.

Penge supports this through liquid-depot projections documented in [ADR-0027](../decisions/0027-liquid-depot-simulation-model.md), combining gross return, expense ratio, tax treatment, dividend yield, and EUR/DKK conversion assumptions.
The household can compare terminal balances or depletion paths under realistic cost and tax inputs.

## Bridge and decumulation

### Story: Plan the bridge from FIRE to pension age

As a household retiring before public and occupational pensions start, I want to simulate monthly withdrawals from liquid assets over a fixed bridge horizon, so that I can test whether the bridge depot lasts until pension income begins.

Penge supports this with bridge decumulation on liquid depots, extending the liquid-depot model documented in [ADR-0027](../decisions/0027-liquid-depot-simulation-model.md).
The model accounts for monthly withdrawals, remaining cost basis, realised gains, progressive Danish aktieindkomst tax, and depletion timing.

### Story: Include dividends during bridge withdrawals

As a household holding distributing realisation funds during the bridge phase, I want dividend distributions and their annual aktieindkomst tax included in the depletion path, so that the required safe monthly withdrawal is not overstated.

Penge now models dividend tax during bridge decumulation for realisation funds as part of the liquid-depot bridge model documented in [ADR-0027](../decisions/0027-liquid-depot-simulation-model.md).
When `annual_dividend_yield` is zero, the bridge behaves like the existing accumulating-fund path.

### Story: Convert pension wealth into retirement income

As a household approaching pension age, I want projected pension wealth converted into monthly Livrente and Ratepension income plus Aldersforsikring lump sum, so that I can reason about gross retirement cashflow rather than only account balances.

Penge supports this through the payout model documented in [ADR-0028](../decisions/0028-sim-payout-model.md).
It models annuity-factor Livrente, PMT-style Ratepension, and lump-sum Aldersforsikring splits.

## Danish tax visibility

### Story: Know whether retirement income triggers Topskat

As a household projecting high pension income, I want to see whether annual gross income exceeds the Topskat threshold, so that I can adjust payout timing or product mix before retirement.

Penge supports this with the DK Topskat exposure model documented in [ADR-0029](../decisions/0029-dk-topskat-folkepension.md).
It reports threshold excess, estimated surtax, and planning suggestions.

### Story: Estimate Folkepension modregning

As a household with private pension income, I want to estimate how much Folkepension pensionstillæg is reduced by private income, so that the public pension component is not over-counted in retirement plans.

Penge supports this with the Folkepension modregning model documented in [ADR-0029](../decisions/0029-dk-topskat-folkepension.md).
It models grundbeløb, pensionstillæg, civil-status-specific thresholds, and income-based reduction.

## How to use these stories

Use these stories as a checklist when adding scenario presets, dashboard views, or MCP tools.
Each user-facing surface should answer one or more of these household questions directly, rather than exposing implementation modules as isolated knobs.
