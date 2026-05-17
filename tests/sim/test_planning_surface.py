"""Tests for explanation-first household planning surfaces."""

from __future__ import annotations

import io
import json
import sys

import pytest

from penge.sim.planning_surface import (
    PlanningSurfaceRequest,
    build_synthetic_household_plan,
    generate_planning_surface,
)
from penge.sim.planning_surface_cli import main as planning_surface_main


def test_planning_surface_answers_core_household_questions() -> None:
    report = generate_planning_surface(
        PlanningSurfaceRequest(
            questions=(
                "can_we_retire",
                "what_breaks_first",
                "how_do_taxes_affect_plan",
                "which_assumptions_matter",
                "which_scenarios_should_we_test",
            )
        )
    )

    answers = {answer.question_id: answer for answer in report.questions}
    assert set(answers) == {
        "can_we_retire",
        "what_breaks_first",
        "how_do_taxes_affect_plan",
        "which_assumptions_matter",
        "which_scenarios_should_we_test",
    }
    assert report.plan_id == "synthetic_household"
    assert report.risks
    assert report.assumptions
    assert report.limitations
    assert answers["can_we_retire"].risk_codes
    assert answers["how_do_taxes_affect_plan"].evidence
    assert answers["which_assumptions_matter"].assumption_keys
    assert answers["which_scenarios_should_we_test"].evidence
    assert "docs/sim/planning-outputs.md" in report.docs


def test_planning_surface_uses_supplied_synthetic_plan() -> None:
    plan = build_synthetic_household_plan().model_copy(update={"horizon_years": 8})

    report = generate_planning_surface(
        PlanningSurfaceRequest(questions=("can_we_retire",)),
        plan=plan,
    )

    assert len(report.questions) == 1
    terminal = next(
        evidence
        for evidence in report.questions[0].evidence
        if evidence.label == "terminal_total_net_worth_dkk"
    )
    assert terminal.value.endswith("DKK")


def test_planning_surface_rejects_duplicate_questions() -> None:
    with pytest.raises(ValueError, match="questions must be unique"):
        PlanningSurfaceRequest(questions=("can_we_retire", "can_we_retire"))


def test_planning_surface_cli_outputs_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "plan_id": "synthetic_household",
                    "questions": ["can_we_retire", "how_do_taxes_affect_plan"],
                }
            )
        ),
    )

    exit_code = planning_surface_main(["--json"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["plan_id"] == "synthetic_household"
    assert [answer["question_id"] for answer in payload["questions"]] == [
        "can_we_retire",
        "how_do_taxes_affect_plan",
    ]
    assert captured.err == ""
