"""Sensitivity and stress-test pack for household plans."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

import pydantic

from penge.sim.balance import project_balance_sheet
from penge.sim.household_scenarios import (
    DelayedPensionStartPreset,
    HigherInflationPreset,
    HigherSpendingPreset,
    HouseholdScenarioPreset,
    LowerReturnsPreset,
    LowerSavingsPreset,
    OneOffExpensePreset,
    apply_scenario_preset,
)
from penge.sim.plan import HouseholdPlan, project_household
from penge.sim.risk import generate_risk_register

__all__ = [
    "HouseholdStressResult",
    "HouseholdStressTestPack",
    "StressTestSpec",
    "default_stress_tests",
    "run_stress_tests",
]

_TWO_DP = Decimal("0.01")
_CRITICAL_RISK_PENALTY_DKK = Decimal("1000000")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)


class StressTestSpec(pydantic.BaseModel):
    """A built-in or caller-provided stress test backed by a scenario preset."""

    model_config = pydantic.ConfigDict(frozen=True)

    name: str
    label: str
    preset: HouseholdScenarioPreset


class HouseholdStressResult(pydantic.BaseModel):
    """Ranked stress-test result for one scenario."""

    model_config = pydantic.ConfigDict(frozen=True)

    name: str
    label: str
    changed_assumptions: tuple[str, ...]
    terminal_net_worth_delta_dkk: Decimal
    terminal_spendable_liquidity_delta_dkk: Decimal
    critical_risk_count_delta: int
    impact_score_dkk: Decimal
    rank: int


class HouseholdStressTestPack(pydantic.BaseModel):
    """Stress-test pack output with baseline context and ranked results."""

    model_config = pydantic.ConfigDict(frozen=True)

    baseline_terminal_net_worth_dkk: Decimal
    baseline_terminal_spendable_liquidity_dkk: Decimal
    results: tuple[HouseholdStressResult, ...]


def default_stress_tests(plan: HouseholdPlan) -> tuple[StressTestSpec, ...]:
    """Return deterministic built-in household stress tests for *plan*."""

    first_projected_year = plan.base_year + 1
    return (
        StressTestSpec(
            name="lower_returns",
            label="Lower returns",
            preset=LowerReturnsPreset(annual_return_delta=Decimal("-0.02")),
        ),
        StressTestSpec(
            name="higher_inflation",
            label="Higher inflation",
            preset=HigherInflationPreset(inflation_rate=plan.inflation_rate + Decimal("0.03")),
        ),
        StressTestSpec(
            name="higher_spending",
            label="Higher spending",
            preset=HigherSpendingPreset(factor=Decimal("1.10")),
        ),
        StressTestSpec(
            name="lower_savings",
            label="Lower savings",
            preset=LowerSavingsPreset(factor=Decimal("0.75")),
        ),
        StressTestSpec(
            name="pension_delay",
            label="Delayed pension start",
            preset=DelayedPensionStartPreset(delay_years=2),
        ),
        StressTestSpec(
            name="one_off_expense",
            label="One-off large expense",
            preset=OneOffExpensePreset(
                year=first_projected_year + 2,
                amount=Decimal("150000"),
                currency="DKK",
                expense_label="stress large expense",
            ),
        ),
    )


def run_stress_tests(
    plan: HouseholdPlan,
    specs: tuple[StressTestSpec, ...] | None = None,
) -> HouseholdStressTestPack:
    """Run stress tests from a household plan and rank by impact."""

    baseline = _metrics(plan)
    stress_specs = specs if specs is not None else default_stress_tests(plan)
    unranked: list[HouseholdStressResult] = []
    for spec in stress_specs:
        scenario = apply_scenario_preset(plan, spec.preset)
        stressed = _metrics(scenario.plan)
        terminal_delta = _q(stressed.terminal_net_worth_dkk - baseline.terminal_net_worth_dkk)
        liquidity_delta = _q(
            stressed.terminal_spendable_liquidity_dkk - baseline.terminal_spendable_liquidity_dkk
        )
        risk_delta = stressed.critical_risk_count - baseline.critical_risk_count
        impact_score = _q(
            abs(terminal_delta)
            + abs(liquidity_delta)
            + Decimal(max(risk_delta, 0)) * _CRITICAL_RISK_PENALTY_DKK
        )
        unranked.append(
            HouseholdStressResult(
                name=spec.name,
                label=spec.label,
                changed_assumptions=scenario.changed_assumptions,
                terminal_net_worth_delta_dkk=terminal_delta,
                terminal_spendable_liquidity_delta_dkk=liquidity_delta,
                critical_risk_count_delta=risk_delta,
                impact_score_dkk=impact_score,
                rank=0,
            )
        )

    ranked = sorted(unranked, key=lambda item: (-item.impact_score_dkk, item.name))
    return HouseholdStressTestPack(
        baseline_terminal_net_worth_dkk=baseline.terminal_net_worth_dkk,
        baseline_terminal_spendable_liquidity_dkk=baseline.terminal_spendable_liquidity_dkk,
        results=tuple(
            item.model_copy(update={"rank": rank}) for rank, item in enumerate(ranked, start=1)
        ),
    )


class _StressMetrics(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    terminal_net_worth_dkk: Decimal
    terminal_spendable_liquidity_dkk: Decimal
    critical_risk_count: int


def _metrics(plan: HouseholdPlan) -> _StressMetrics:
    result = project_household(plan)
    balance = project_balance_sheet(result)
    terminal = balance.rows[-1]
    risks = generate_risk_register(result, balance_sheet=balance)
    return _StressMetrics(
        terminal_net_worth_dkk=terminal.total_net_worth_dkk,
        terminal_spendable_liquidity_dkk=terminal.spendable_liquidity_dkk,
        critical_risk_count=sum(1 for finding in risks.findings if finding.severity == "critical"),
    )
