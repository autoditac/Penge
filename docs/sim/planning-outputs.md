# Household Planning Outputs

The household planning output layer turns a `HouseholdProjectionResult` into
decision-facing artefacts.
It keeps the simulation primitives auditable while answering household questions
in plain language.

## Bridge safe-spending planner

Use `assess_bridge_spending()` when a bridge depot already exists and the
question is how much monthly net spending it can safely support until pension
income begins.
The function wraps the existing bridge decumulation model, so ASK/lager tax,
realisationsbeskatning withdrawal tax, and dividend tax for distributing
realisation funds stay consistent with `compute_bridge_pmt()`.

```python
from decimal import Decimal

from penge.sim.bridge_spending import assess_bridge_spending
from penge.sim.liquid import BridgeConfig

config = BridgeConfig(
    starting_balance_dkk=Decimal("1000000"),
    cost_basis_dkk=Decimal("1000000"),
    horizon_months=120,
    gross_annual_return_rate=Decimal("0.05"),
    annual_expense_ratio=Decimal("0.005"),
    account_type="ask",
    tax_regime="lager",
    aktieindkomst_threshold_dkk=Decimal("67500"),
)

result = assess_bridge_spending(
    config,
    target_monthly_net_spending_dkk=Decimal("8000"),
    start_year=2056,
)
```

Use `required_starting_capital_for_bridge_spending()` for the inverse question:
how much bridge capital is needed for a target monthly net spending level.
For realisation funds the search preserves the input cost-basis ratio; for ASK
and lager funds the searched cost basis follows the searched balance because the
account is marked to market.

## Balance sheet and liquidity runway

`project_balance_sheet()` derives yearly rows from a household projection.
Each row separates:

- ASK balances;
- frie midler balances;
- active bridge drawdown balances;
- locked pension balances;
- home value, mortgage debt, and home equity;
- spendable liquidity;
- total net worth;
- spending runway in months.

This distinction matters because a household can look wealthy on total net
worth while still failing the bridge phase if spendable liquidity is depleted.
When a liquid account is used by a bridge template, the balance-sheet projection
uses the accumulation account through the bridge start year and then replaces it
with the bridge drawdown balance in later years.
Home equity is included in total net worth but excluded from spendable liquidity.
If a property sale is explicitly modelled, released net sale proceeds are added
to the real-estate cash adjustment.
Purchase costs, mortgage interest, and recurring housing costs reduce that same
cash adjustment so liquidity runway does not treat unpaid housing costs as free.

## Real-estate and mortgage scenarios

`penge.sim.real_estate` projects property value, mortgage debt, recurring
ownership costs, interest, amortisation, equity, and explicit sale proceeds.
`HouseholdPlan.real_estate_assets` and `HouseholdPlan.mortgages` make those rows
available to `project_household()` and `project_balance_sheet()`.

```python
from decimal import Decimal

from penge.sim.plan import HouseholdPlan, project_household
from penge.sim.real_estate import MortgageConfig, PropertyAssetConfig

plan = HouseholdPlan(
    ...,
    real_estate_assets=(
        PropertyAssetConfig(
            property_id="home",
            label="Family home",
            start_year=2027,
            value_dkk=Decimal("3500000"),
            annual_value_growth_rate=Decimal("0.02"),
            annual_recurring_cost_dkk=Decimal("25000"),
        ),
    ),
    mortgages=(
        MortgageConfig(
            mortgage_id="home-loan",
            property_id="home",
            start_year=2027,
            principal_dkk=Decimal("2500000"),
            annual_interest_rate=Decimal("0.035"),
            annual_amortization_dkk=Decimal("80000"),
        ),
    ),
)

projection = project_household(plan)
```

The model is planning-grade and deterministic.
It does not model refinancing, variable-rate reset schedules, tax deductibility,
or rental-income taxation.
Direct `PropertyAssetConfig.purchase_cost_dkk` values affect balance-sheet
liquidity even when the property was not created through `HomePurchasePreset`.
Use `HomePurchasePreset` for a future purchase scenario and
`HigherMortgageRatePreset` for interest-rate sensitivity in the stress pack.

## Retirement readiness report

`generate_readiness_report()` composes the balance sheet, bridge safe-spending
summary, tax timeline, tax-country context, risk register, contribution strategy,
pension payout, Folkepension, and audit assumptions into a structured
`RetirementReadinessReport`.
The report exposes both machine-readable findings and deterministic Markdown.

```python
from penge.sim.plan import project_household
from penge.sim.readiness import generate_readiness_report

projection = project_household(plan)
report = generate_readiness_report(projection)

print(report.conclusion)
print(report.markdown)
```

Example Markdown sections:

```markdown
# Retirement readiness report

**Conclusion:** watch
**Planned retirement year:** 2055

## Findings

| Severity | Code | Year | Finding | Next action |
| --- | --- | ---: | --- | --- |
| warning | `folkepension_reduced` | n/a | alice Folkepension pension supplement is reduced by 1,234.00 DKK/month. | Review private pension payout level and means-test assumptions. |

## Bridge summary

| Horizon | Max net monthly spending | Depletion | Tax paid |
| ---: | ---: | ---: | ---: |
| 120 months | 10,000.00 DKK | 2065 | 50,000.00 DKK |
```

Pass a `ContributionStrategyExplanation` as `contribution_strategy=` when the
report should include the ASK/frie-midler routing summary in the same Markdown
artifact.

## Household tax event timeline

`build_tax_timeline()` derives a year-by-year `TaxTimeline` from a
`HouseholdProjectionResult`.
It attributes visible tax drag to liquid depots, bridge withdrawals and
dividends, PAL-skat, Topskat exposure, and Folkepension modregning.

```python
from penge.sim.plan import project_household
from penge.sim.tax_timeline import build_tax_timeline

projection = project_household(plan)
timeline = build_tax_timeline(projection)

print(timeline.totals.total_tax_drag_dkk)
```

Rows include both per-tax amounts and account-level attributions.
Warnings are deterministic and currently cover Topskat exposure, Folkepension
modregning, and material year-over-year changes in total tax drag.
`total_tax_drag_dkk` intentionally excludes Folkepension modregning because that
is a means-tested public-pension benefit reduction, not tax owed.
The Topskat value is a gross-salary planning estimate; use the statutory tax
engine for filing-grade Topskat calculations.

## DK/DE tax-country context

`build_household_tax_context()` summarizes member-level tax-country assumptions
from `HouseholdPlan.members` and `TaxConfig`.
`HouseholdMember.tax_country` is optional and defaults to `jurisdiction`, but it
can be set explicitly when residence and tax treatment need to be reviewed
separately.

The readiness report renders a tax-country assumptions table with salary,
pension-return, pension-drawdown, and liquid capital-gains planning rates.
For DE members it also surfaces unsupported areas:

- Vorabpauschale timing is not projected per fund inside `HouseholdPlan`.
- Splittingtarif, Kirchensteuer, Soli, allowances, and exact pension
  Besteuerungsanteil are not computed by the household planner.

Those warnings are intentionally visible in the risk register so mixed DK/DE
plans do not silently treat a German spouse's depot as Danish.

## Planning risk register

`generate_risk_register()` converts projection outputs into named, actionable
findings.
Each `PlanningRiskFinding` carries a stable code, severity, affected year,
source assumption, and next action.

```python
from penge.sim.risk import generate_risk_register

register = generate_risk_register(projection)
for finding in register.findings:
    print(finding.code, finding.severity, finding.next_action)
```

The readiness report uses the same risk register internally, so the Markdown
findings table and machine-readable risk output stay aligned.

## ASK and contribution strategy explainer

`explain_contribution_strategy()` wraps the existing `ContributionRouter` and
monthly/yearly routing simulations in a deterministic explanation object.
It reports total routed to ASK and frie midler, the exact cap-exhaustion month
and calendar year when applicable, onward monthly split, warnings, and a
plain-language summary.

```python
from decimal import Decimal

from penge.sim.contribution_strategy import explain_contribution_strategy
from penge.sim.routing import ContributionRouter

router = ContributionRouter(
    ask_cap_dkk=Decimal("142500"),
    ask_cumulative_deposits_dkk=Decimal("62000"),
    monthly_contribution_dkk=Decimal("10000"),
)

strategy = explain_contribution_strategy(router, base_year=2024, horizon_years=5)
```

Use this output beside the tax timeline and risk register when explaining why
new savings should move from ASK to frie midler after the ASK lifetime deposit
cap is exhausted.

## Scenario presets and cookbook

`penge.sim.household_scenarios` provides typed presets that derive labelled
`HouseholdScenario` objects from a baseline `HouseholdPlan`.
The presets are deterministic transformations, not ad-hoc mutation of low-level
model fields.

Built-in presets cover common household questions:

| Preset | Use case |
| --- | --- |
| `RetireInYearPreset` | Move retirement, bridge, and payout start years together. |
| `WorkReductionPreset` | Model one member reducing salary and salary-linked pension accrual. |
| `IncreasedSavingsPreset` / `LowerSavingsPreset` | Change liquid savings budgets. |
| `LowerReturnsPreset` | Reduce pension, liquid, and bridge return assumptions. |
| `HigherInflationPreset` | Raise plan and spending inflation assumptions. |
| `HigherSpendingPreset` | Scale household spending needs. |
| `OneOffExpensePreset` | Add a one-off large expense. |
| `DelayedPensionStartPreset` | Delay public pension access assumptions. |

```python
from decimal import Decimal

from penge.sim.household_scenarios import (
    HigherSpendingPreset,
    RetireInYearPreset,
    compose_scenario_presets,
)

scenario = compose_scenario_presets(
    plan,
    (
        RetireInYearPreset(year=2032),
        HigherSpendingPreset(factor=Decimal("1.10")),
    ),
    name="retire-2032-higher-spend",
    label="Retire in 2032 with 10% higher spending",
)
```

Presets are composable where they keep the resulting `HouseholdPlan` valid.
The output carries a label and changed-assumptions list so reports, stress packs,
or dashboards can explain what changed.

## Sensitivity and stress-test pack

`run_stress_tests()` runs built-in or caller-provided stress scenarios from a
`HouseholdPlan`.
It ranks results by a deterministic impact score based on terminal net-worth
delta, terminal spendable-liquidity delta, and new critical risk findings.

```python
from penge.sim.stress import run_stress_tests

pack = run_stress_tests(plan)
for result in pack.results:
    print(result.rank, result.label, result.impact_score_dkk)
```

The default pack includes lower returns, higher inflation, higher spending,
lower savings, delayed pension start, and a one-off expense.
Stress ranking is a prioritization aid: it highlights which assumptions deserve
attention first, but it does not assign probabilities to the stressed outcomes.

## Tax-aware drawdown-order planner

`penge.sim.drawdown` compares planning-only drawdown orders across cash, ASK,
frie midler, and pension buckets.
It can build starting buckets from a `HouseholdProjectionResult`, or callers can
provide explicit `DrawdownAccountState` values.

```python
from decimal import Decimal

from penge.sim.drawdown import build_drawdown_accounts, compare_drawdown_strategies
from penge.sim.plan import project_household

projection = project_household(plan)
accounts = build_drawdown_accounts(
    projection,
    start_year=2030,
    cash_balance_dkk=Decimal("100000"),
)
results = compare_drawdown_strategies(
    accounts,
    start_year=2030,
    annual_spending_dkk=Decimal("300000"),
    horizon_years=8,
)
```

Outputs include yearly gross withdrawals, net spending funded, estimated tax,
depletion timing, and remaining balances by bucket.
The planner respects configured pension accessibility years, estimates
realisationsbeskatning tax for frie midler withdrawals from the current gain
fraction, estimates ASK tax on latent gains with the account `tax_rate`
(`ASK_RATE` for accounts built from projections), and applies a flat pension
drawdown `tax_rate` after accessibility checks.
It does not model exact personal-income tax brackets, loss carry-forwards, future
portfolio growth during the drawdown horizon, or filing-grade pension tax.
It is planning support only, not automated trading, rebalancing, or tax-filing
advice.

## Source-backed planning assumptions

`penge.sim.source_assumptions` extracts reviewable planning assumptions from
parsed or OCR sidecar text.
It is deterministic and rule-based.
It does not send document text to an LLM or any external service.

```python
from pathlib import Path

from penge.sim.source_assumptions import (
    ParsedPlanningDocument,
    accept_planning_assumption,
    extract_planning_assumptions,
)

document = ParsedPlanningDocument(
    document_id="synthetic-pfa-2026",
    path=Path("vault/2026/pension/synthetic.txt"),
    classification="pfa",
    extracted_via="ocr",
    text="Pensionssaldo: 1200000 EUR\nÅOP: 0.45%",
)

suggestions = extract_planning_assumptions((document,))
accepted = accept_planning_assumption(suggestions[0])
```

Extracted assumptions carry source provenance: document ID, path, classification,
extraction method, and text excerpt.
They start as `suggested` and must be accepted before a caller copies the value
into `HouseholdPlan`.
Supported assumption kinds currently include pension balance, annuity factor,
cost basis, ÅOP, dividend yield, property value, and mortgage balance.

## Explanation-first planning surface

`generate_planning_surface()` packages the household planner into direct answers
for dashboard and MCP consumers.
It runs one `HouseholdPlan`, generates the readiness report and stress-test pack,
and returns answers linked to evidence, assumption keys, risk codes, limitations,
and documentation.

```python
from penge.sim.planning_surface import PlanningSurfaceRequest, generate_planning_surface

surface = generate_planning_surface(
    PlanningSurfaceRequest(
        questions=(
            "can_we_retire",
            "what_breaks_first",
            "how_do_taxes_affect_plan",
        )
    )
)
for answer in surface.questions:
    print(answer.question, answer.answer)
```

The built-in `synthetic_household` plan is synthetic and exists for tests, demos,
and the MCP golden-question suite.
It is not a personal household plan.
The surface currently answers:

| Question id | Direct household question |
| --- | --- |
| `can_we_retire` | Can this household retire on the planned timeline? |
| `what_breaks_first` | What breaks first if the plan fails? |
| `how_do_taxes_affect_plan` | How do taxes affect this plan? |
| `which_assumptions_matter` | Which assumptions should be reviewed before deciding? |
| `which_scenarios_should_we_test` | Which stress scenarios should be tested first? |

The MCP tool `answer_planning_question` exposes the same surface without sending a
raw plan or raw document text over the wire.
Returned answers include `assumption_keys`, `risk_codes`, and `limitation_codes`
so a UI or LLM host can show the explanation and the audit trail together.

## Finding semantics

Readiness findings use stable `code` values and one of three severities:

| Severity | Meaning |
| --- | --- |
| `info` | No immediate action is required. |
| `warning` | A modelling assumption or tax effect materially changes the plan. |
| `critical` | The plan fails a hard readiness check, such as liquidity depletion. |

The implemented checks are:

| Code | Trigger |
| --- | --- |
| `liquidity_depleted` | Spendable liquidity is zero while annual spending remains positive. |
| `locked_pension_before_access` | Pension wealth exists but spendable liquidity is gone before pension access. |
| `topskat_exposure` | DK income exceeds the configured Topskat threshold. |
| `material_tax_drag_change` | Total tax drag changes materially versus the prior year. |
| `folkepension_reduced` | Folkepension pension supplement is reduced by private pension income. |
| `folkepension_tillaeg_fully_reduced` | Folkepension pension supplement is fully reduced by private pension income. |
| `ask_cap_reached` | ASK contributions overflow after the lifetime deposit cap is reached. |
| Contribution strategy warning code | Warning emitted by `explain_contribution_strategy()`. |
| Projection warning code | Any warning emitted by `project_household()`. |
