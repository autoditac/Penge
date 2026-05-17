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
- spendable liquidity;
- total net worth;
- spending runway in months.

This distinction matters because a household can look wealthy on total net
worth while still failing the bridge phase if spendable liquidity is depleted.
When a liquid account is used by a bridge template, the balance-sheet projection
uses the accumulation account through the bridge start year and then replaces it
with the bridge drawdown balance in later years.

## Retirement readiness report

`generate_readiness_report()` composes the balance sheet, bridge safe-spending
summary, tax timeline, risk register, contribution strategy, pension payout,
Folkepension, and audit assumptions into a structured `RetirementReadinessReport`.
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
