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
summary, projection warnings, pension payout, Folkepension, tax drag, and audit
assumptions into a structured `RetirementReadinessReport`.
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

## Finding semantics

Readiness findings use stable `code` values and one of three severities:

| Severity | Meaning |
| --- | --- |
| `info` | No immediate action is required. |
| `warning` | A modelling assumption or tax effect materially changes the plan. |
| `critical` | The plan fails a hard readiness check, such as liquidity depletion. |

The first implemented checks are:

| Code | Trigger |
| --- | --- |
| `liquidity_depleted` | Spendable liquidity is zero while annual spending remains positive. |
| `bridge_depletes_early` | Bridge simulation ends materially below zero before the requested horizon. |
| `folkepension_reduced` | Folkepension pension supplement is reduced by private pension income. |
| Projection warning code | Any warning emitted by `project_household()`. |
