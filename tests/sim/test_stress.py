"""Tests for household stress-test packs."""

from __future__ import annotations

from penge.sim.stress import default_stress_tests, run_stress_tests
from tests.sim.planning_output_helpers import household_output_plan


def test_default_stress_tests_include_ranked_builtin_scenarios() -> None:
    plan = household_output_plan()

    specs = default_stress_tests(plan)
    pack = run_stress_tests(plan, specs)

    assert {spec.name for spec in specs} >= {
        "lower_returns",
        "higher_inflation",
        "higher_spending",
        "lower_savings",
        "pension_delay",
    }
    assert len(pack.results) >= 5
    assert [result.rank for result in pack.results] == list(range(1, len(pack.results) + 1))
    assert pack.results[0].impact_score_dkk >= pack.results[-1].impact_score_dkk
    assert all(result.changed_assumptions for result in pack.results)
    assert pack.baseline_terminal_net_worth_dkk > 0
