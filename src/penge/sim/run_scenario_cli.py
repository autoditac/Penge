"""JSON CLI wrapper around the Penge scenario engine (issue #47).

Stable contract used by the MCP ``run_scenario`` tool. The TypeScript
side cannot construct Pydantic models or run NumPy-backed Monte-Carlo,
so it shells out to this CLI: JSON spec on stdin, JSON summary on
stdout.

Invocation::

    python -m penge.sim.run_scenario_cli --json < spec.json

The ``--json`` flag is accepted for parity with the issue's wire
contract; JSON I/O is in fact the only mode.

Input schema (all keys required unless noted)::

    {
      "cashflow":     {... CashflowConfig dump ...},
      "tax":          {... TaxConfig dump (optional, defaults to enabled=False) ...},
      "goal":         {... GoalConfig dump ...},
      "return_model": {... BootstrapReturnModel dump (asset_returns,
                            inflation, block_months, seed) ...},
      "mc":           {... MonteCarloConfig dump ...},
      "scenario":     {"type": "house_purchase" | "work_reduction",
                       "params": {...}},
      "monte_carlo":  {"paths": int,
                       "seed": int | null (optional),
                       "horizon_years": int}
    }

The ``monte_carlo`` block is the wire-level override that the MCP tool
forwards from the LLM host:

* ``paths`` overrides ``mc.n_paths``,
* ``horizon_years`` overrides ``cashflow.horizon_years``,
* ``seed`` (when present) overrides ``return_model.seed``.

Output schema (matches the MCP wire schema)::

    {
      "baseline": {
        "p10": {"<year>": <eur>, ...},
        "p50": {"<year>": <eur>, ...},
        "p90": {"<year>": <eur>, ...},
        "fire_year_distribution": {"<year>": <count>, ...}
      },
      "scenario": {... same shape ...},
      "deltas": {
        "p50_value_eur":      <float | null>,
        "fire_year_shift_years": <int | null>
      }
    }

``p50_value_eur`` is the terminal-year (largest year key in baseline.p50)
delta ``scenario.p50 - baseline.p50``. ``fire_year_shift_years`` is
``scenario.median_fire_year - baseline.median_fire_year``; either is
``null`` when the corresponding median FIRE year is undefined (fewer
than 50 % of paths met the goal).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from penge.sim.cashflow import CashflowConfig
from penge.sim.goal import GoalConfig
from penge.sim.montecarlo import MonteCarloConfig, MonteCarloResult
from penge.sim.returns import BootstrapReturnModel
from penge.sim.scenario import (
    HousePurchaseScenario,
    Scenario,
    ScenarioError,
    WorkReductionScenario,
    compare,
)
from penge.sim.tax import TaxConfig

__all__ = ["main", "run_scenario"]


class CliError(Exception):
    """Raised on invalid CLI arguments or input JSON."""


def _build_scenario(spec: Mapping[str, Any]) -> Scenario:
    if not isinstance(spec, Mapping):
        raise CliError("scenario must be an object")
    stype = spec.get("type")
    params = spec.get("params") or {}
    if not isinstance(params, Mapping):
        raise CliError("scenario.params must be an object")
    if stype == "house_purchase":
        return HousePurchaseScenario(**dict(params))
    if stype == "work_reduction":
        return WorkReductionScenario(**dict(params))
    raise CliError(
        f"unknown scenario.type {stype!r}; expected 'house_purchase' or 'work_reduction'"
    )


def _terminal_year_p50_delta(
    baseline: MonteCarloResult, scenario: MonteCarloResult
) -> float | None:
    if not baseline.p50_portfolio:
        return None
    terminal_year = max(baseline.p50_portfolio.keys())
    base_v = baseline.p50_portfolio.get(terminal_year)
    scen_v = scenario.p50_portfolio.get(terminal_year)
    if base_v is None or scen_v is None:
        return None
    return float(scen_v - base_v)


def _fire_shift(baseline: MonteCarloResult, scenario: MonteCarloResult) -> int | None:
    if baseline.median_fire_year is None or scenario.median_fire_year is None:
        return None
    return int(scenario.median_fire_year - baseline.median_fire_year)


def _summarise(result: MonteCarloResult) -> dict[str, Any]:
    def floats(d: Mapping[int, Decimal]) -> dict[str, float]:
        return {str(year): float(value) for year, value in sorted(d.items())}

    return {
        "p10": floats(result.p10_portfolio),
        "p50": floats(result.p50_portfolio),
        "p90": floats(result.p90_portfolio),
        "fire_year_distribution": {
            str(year): int(count) for year, count in sorted(result.fire_year_distribution.items())
        },
    }


def run_scenario(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Pure entry point: build configs from *spec* and run the comparison."""
    if not isinstance(spec, Mapping):
        raise CliError("input must be a JSON object at the top level")

    overrides = spec.get("monte_carlo") or {}
    if not isinstance(overrides, Mapping):
        raise CliError("monte_carlo must be an object")
    try:
        paths = int(overrides["paths"])
        horizon_years = int(overrides["horizon_years"])
    except KeyError as exc:
        raise CliError(f"monte_carlo missing required key {exc.args[0]!r}") from exc
    except (TypeError, ValueError) as exc:
        raise CliError(f"monte_carlo: {exc}") from exc
    seed_override = overrides.get("seed")

    if "cashflow" not in spec:
        raise CliError("input missing 'cashflow' block")
    if "goal" not in spec:
        raise CliError("input missing 'goal' block")
    if "return_model" not in spec:
        raise CliError("input missing 'return_model' block")
    if "mc" not in spec:
        raise CliError("input missing 'mc' block")

    cashflow_raw = dict(spec["cashflow"])
    cashflow_raw["horizon_years"] = horizon_years
    cashflow_cfg = CashflowConfig(**cashflow_raw)

    tax_cfg = TaxConfig(**dict(spec.get("tax") or {}))
    goal_cfg = GoalConfig(**dict(spec["goal"]))

    rm_raw = dict(spec["return_model"])
    if seed_override is not None:
        rm_raw["seed"] = int(seed_override)
    return_model = BootstrapReturnModel(**rm_raw)

    mc_raw = dict(spec["mc"])
    mc_raw["n_paths"] = paths
    mc_cfg = MonteCarloConfig(**mc_raw)

    scenario = _build_scenario(spec.get("scenario") or {})

    comparison = compare(
        cashflow_cfg,
        tax_cfg,
        goal_cfg,
        return_model,
        mc_cfg,
        {"scenario": scenario},
    )

    baseline = comparison.baseline
    scenario_result = comparison.scenarios[0].mc_result

    return {
        "baseline": _summarise(baseline),
        "scenario": _summarise(scenario_result),
        "deltas": {
            "p50_value_eur": _terminal_year_p50_delta(baseline, scenario_result),
            "fire_year_shift_years": _fire_shift(baseline, scenario_result),
        },
    }


def _read_stdin_json() -> Mapping[str, Any]:
    text = sys.stdin.read()
    if not text.strip():
        raise CliError("no JSON received on stdin")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CliError(f"input is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CliError("input JSON must be an object at the top level")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="penge-sim-run-scenario",
        description="Run a baseline + scenario Monte-Carlo comparison and emit a JSON summary.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Read JSON from stdin (default; flag accepted for symmetry).",
    )
    parser.parse_args(argv)

    try:
        spec = _read_stdin_json()
        result = run_scenario(spec)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors()
        )
        print(f"error: invalid input: {details}", file=sys.stderr)
        return 2
    except ScenarioError as exc:
        print(f"error: scenario invalid: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - last-resort guard
        print(f"error: {exc}", file=sys.stderr)
        return 1

    json.dump(result, sys.stdout, separators=(",", ":"), sort_keys=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
