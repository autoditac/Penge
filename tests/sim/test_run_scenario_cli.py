"""Tests for penge.sim.run_scenario_cli — JSON CLI wrapper."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

import pytest

from penge.sim.run_scenario_cli import CliError, main, run_scenario


def _baseline_spec() -> dict[str, Any]:
    return {
        "cashflow": {
            "base_year": 2024,
            "horizon_years": 10,
            "inflation_rate": "0.02",
            "eur_per_dkk": "0.134",
            "salaries": [{"entity": "person_dk", "gross_annual": "80000"}],
            "contributions": [],
            "pension_rules": [],
        },
        "tax": {},
        "goal": {"target_annual_eur": "50000"},
        "return_model": {
            "asset_returns": {"equity": ["0.005"] * 120},
            "inflation": {"dk": ["0.002"] * 120},
            "block_months": 12,
            "seed": 42,
        },
        "mc": {
            "n_paths": 50,
            "asset_weights": {"equity": "1"},
            "initial_portfolio_eur": "200000",
        },
    }


def _full_spec(scenario: dict[str, Any], paths: int = 50, seed: int = 42) -> dict[str, Any]:
    spec = _baseline_spec()
    spec["scenario"] = scenario
    spec["monte_carlo"] = {"paths": paths, "seed": seed, "horizon_years": 10}
    return spec


class TestRunScenario:
    def test_work_reduction_returns_summary(self) -> None:
        spec = _full_spec(
            {
                "type": "work_reduction",
                "params": {"entity": "person_dk", "year": 2027, "fte_fraction": "0.8"},
            }
        )
        out = run_scenario(spec)
        assert set(out.keys()) == {"baseline", "scenario", "deltas"}
        for branch in ("baseline", "scenario"):
            summary = out[branch]
            assert set(summary.keys()) == {"p10", "p50", "p90", "fire_year_distribution"}
            assert len(summary["p50"]) == 10
            for key in summary["p50"]:
                assert key.isdigit() and len(key) == 4
        assert "p50_value_eur" in out["deltas"]
        assert "fire_year_shift_years" in out["deltas"]

    def test_house_purchase_branch(self) -> None:
        spec = _full_spec(
            {
                "type": "house_purchase",
                "params": {
                    "year": 2026,
                    "price_eur": "300000",
                    "downpayment_eur": "60000",
                    "mortgage_rate": "0.02",
                    "term_years": 20,
                },
            }
        )
        out = run_scenario(spec)
        # House purchase reduces initial portfolio by 60000 → scenario p50
        # should be lower than baseline at the terminal year.
        terminal = max(out["baseline"]["p50"].keys())
        assert out["scenario"]["p50"][terminal] < out["baseline"]["p50"][terminal]
        delta = out["deltas"]["p50_value_eur"]
        assert delta is not None and delta < 0

    def test_unknown_scenario_type(self) -> None:
        spec = _full_spec({"type": "magic", "params": {}})
        with pytest.raises(CliError, match=r"unknown scenario\.type"):
            run_scenario(spec)

    def test_missing_block(self) -> None:
        spec = _full_spec(
            {
                "type": "work_reduction",
                "params": {"entity": "p", "year": 2027, "fte_fraction": "0.8"},
            }
        )
        del spec["cashflow"]
        with pytest.raises(CliError, match="cashflow"):
            run_scenario(spec)

    def test_non_mapping_block_raises_clierror(self) -> None:
        spec = _full_spec(
            {
                "type": "work_reduction",
                "params": {"entity": "p", "year": 2027, "fte_fraction": "0.8"},
            }
        )
        spec["cashflow"] = "not an object"
        with pytest.raises(CliError, match="must be an object"):
            run_scenario(spec)

    def test_invalid_seed_override_raises_clierror(self) -> None:
        spec = _full_spec(
            {
                "type": "work_reduction",
                "params": {"entity": "person_dk", "year": 2027, "fte_fraction": "0.8"},
            }
        )
        spec["monte_carlo"]["seed"] = "not-an-int"
        with pytest.raises(CliError, match="seed must be an integer"):
            run_scenario(spec)

    def test_monte_carlo_overrides_applied(self) -> None:
        spec = _full_spec(
            {
                "type": "work_reduction",
                "params": {"entity": "person_dk", "year": 2027, "fte_fraction": "0.8"},
            },
            paths=25,
        )
        spec["monte_carlo"]["horizon_years"] = 5
        out = run_scenario(spec)
        # horizon_years override propagates to cashflow → 5 years of p50.
        assert len(out["baseline"]["p50"]) == 5

    def test_seed_determinism(self) -> None:
        scenario = {
            "type": "work_reduction",
            "params": {"entity": "person_dk", "year": 2027, "fte_fraction": "0.8"},
        }
        a = run_scenario(_full_spec(scenario, seed=123))
        b = run_scenario(_full_spec(scenario, seed=123))
        assert a == b


class TestMain:
    def test_main_reads_stdin_and_emits_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _full_spec(
            {
                "type": "work_reduction",
                "params": {"entity": "person_dk", "year": 2027, "fte_fraction": "0.8"},
            }
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(spec)))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--json"])
        assert rc == 0
        parsed = json.loads(buf.getvalue())
        assert "baseline" in parsed and "scenario" in parsed and "deltas" in parsed

    def test_main_returns_2_on_invalid_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["--json"])
        assert rc == 2
        assert "not valid JSON" in err.getvalue()

    def test_main_returns_2_on_empty_stdin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["--json"])
        assert rc == 2
        assert "no JSON" in err.getvalue()

    def test_main_returns_2_on_validation_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _full_spec(
            {
                "type": "work_reduction",
                "params": {"entity": "person_dk", "year": 2027, "fte_fraction": "0.8"},
            }
        )
        # mortgage rate > 1 → validation error in HousePurchaseScenario
        spec["scenario"] = {
            "type": "house_purchase",
            "params": {
                "year": 2026,
                "price_eur": "300000",
                "downpayment_eur": "60000",
                "mortgage_rate": "5",
                "term_years": 20,
            },
        }
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(spec)))
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["--json"])
        assert rc == 2
        assert "invalid input" in err.getvalue()

    def test_main_returns_2_on_scenario_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # downpayment exceeds portfolio → ScenarioError
        spec = _full_spec(
            {
                "type": "house_purchase",
                "params": {
                    "year": 2026,
                    "price_eur": "300000",
                    "downpayment_eur": "300000",
                    "mortgage_rate": "0.02",
                    "term_years": 20,
                },
            }
        )
        spec["mc"]["initial_portfolio_eur"] = "100000"
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(spec)))
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["--json"])
        assert rc == 2
        assert "scenario invalid" in err.getvalue()
