"""Scenario engine — diffs over a baseline Monte-Carlo run.

A *scenario* is a mutation applied to a :class:`~penge.sim.cashflow.CashflowProjection`
(and optionally the :class:`~penge.sim.montecarlo.MonteCarloConfig`) that
models a real-world household decision. The engine re-runs Monte-Carlo for
each scenario and returns side-by-side comparison data.

Public API
----------
- :class:`HousePurchaseScenario` — models a property acquisition
- :class:`WorkReductionScenario` — models a reduction in working hours
- :class:`ScenarioResult` — the output for a single scenario
- :class:`ScenarioComparison` — baseline vs. one or more scenarios
- :func:`compare` — runs baseline + all scenarios; returns a comparison
- :exc:`ScenarioError` — raised when a scenario produces an invalid state
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from pydantic import BaseModel, Field, model_validator

from penge.sim.cashflow import CashflowConfig, CashflowProjection, YearlyFlow, project
from penge.sim.goal import GoalConfig
from penge.sim.montecarlo import MonteCarloConfig, MonteCarloResult, run
from penge.sim.returns import BootstrapReturnModel
from penge.sim.tax import TaxConfig

__all__ = [
    "HousePurchaseScenario",
    "ScenarioComparison",
    "ScenarioError",
    "ScenarioResult",
    "WorkReductionScenario",
    "compare",
]

_TWO_DP = Decimal("0.01")


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------


class HousePurchaseScenario(BaseModel, frozen=True):
    """Model a one-off property acquisition.

    The down-payment reduces ``initial_portfolio_eur`` in the Monte-Carlo
    config.  Annual mortgage repayments are deducted from
    ``liquid_contribution_eur`` of the first entity in the projection for
    each year between *year* and ``year + term_years - 1`` (inclusive).

    All monetary amounts are in EUR.
    """

    year: int = Field(..., ge=2024, le=2100, description="Calendar year of purchase")
    price_eur: Decimal = Field(..., gt=Decimal("0"), description="Full purchase price")
    downpayment_eur: Decimal = Field(
        ..., gt=Decimal("0"), description="Down-payment deducted from the portfolio"
    )
    mortgage_rate: Decimal = Field(
        ...,
        ge=Decimal("0"),
        le=Decimal("1"),
        description="Annual nominal interest rate (0-1)",
    )
    term_years: int = Field(..., ge=1, le=50, description="Mortgage term in years")

    @model_validator(mode="after")
    def _downpayment_le_price(self) -> HousePurchaseScenario:
        if self.downpayment_eur > self.price_eur:
            raise ValueError("downpayment_eur must not exceed price_eur")
        return self

    def annual_payment_eur(self) -> Decimal:
        """Compute constant annual mortgage payment (annuity formula).

        Returns ``Decimal("0")`` when the property is bought outright
        (``downpayment_eur == price_eur``).
        """
        principal = self.price_eur - self.downpayment_eur
        if principal <= 0:
            return Decimal("0")
        r = float(self.mortgage_rate)
        n = self.term_years
        if r == 0.0:
            payment = float(principal) / n
        else:
            payment = float(principal) * r / (1.0 - (1.0 + r) ** (-n))
        return Decimal(str(round(payment, 2)))

    def apply(
        self, proj: CashflowProjection, mc_cfg: MonteCarloConfig
    ) -> tuple[CashflowProjection, MonteCarloConfig]:
        """Return modified (projection, mc_cfg) with the purchase applied.

        The down-payment is subtracted from ``mc_cfg.initial_portfolio_eur``.
        The annual mortgage payment is deducted from ``liquid_contribution_eur``
        of the first entity found in the projection for the mortgage years.

        Args:
            proj: Gross cashflow projection to modify.
            mc_cfg: Monte-Carlo configuration to modify.

        Returns:
            ``(new_proj, new_mc_cfg)`` — originals are not mutated.
        """
        new_portfolio = mc_cfg.initial_portfolio_eur - self.downpayment_eur
        payment = self.annual_payment_eur()

        new_flows: list[YearlyFlow] = []
        entities = proj.entities()
        first_entity = entities[0] if entities else None
        end_year = self.year + self.term_years - 1

        for flow in proj.flows:
            if payment > 0 and flow.entity == first_entity and self.year <= flow.year <= end_year:
                new_flows.append(
                    flow.model_copy(
                        update={
                            "liquid_contribution_eur": (
                                flow.liquid_contribution_eur - payment
                            ).quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)
                        }
                    )
                )
            else:
                new_flows.append(flow)

        new_proj = CashflowProjection(config=proj.config, flows=tuple(new_flows))
        new_mc = mc_cfg.model_copy(update={"initial_portfolio_eur": new_portfolio})
        return new_proj, new_mc


class WorkReductionScenario(BaseModel, frozen=True):
    """Model a reduction in working hours for one entity.

    From *year* onward, the entity's ``gross_salary_eur`` and
    ``pension_accrual_eur`` are scaled by *fte_fraction*.
    ``liquid_contribution_eur`` is left unchanged (it is an explicit savings
    budget, not derived from salary in the cashflow model).

    ``cumulative_pension_eur`` is recomputed from the new accruals from
    *year* onward.
    """

    entity: str = Field(..., min_length=1)
    year: int = Field(..., ge=2024, le=2100, description="First year the reduction takes effect")
    fte_fraction: Decimal = Field(
        ...,
        gt=Decimal("0"),
        le=Decimal("1"),
        description="New FTE fraction (e.g. 0.8 = 80 %)",
    )

    def apply(
        self, proj: CashflowProjection, mc_cfg: MonteCarloConfig
    ) -> tuple[CashflowProjection, MonteCarloConfig]:
        """Return modified (projection, mc_cfg) with salary reduced from *year*.

        Args:
            proj: Gross cashflow projection to modify.
            mc_cfg: Monte-Carlo configuration (returned unchanged).

        Returns:
            ``(new_proj, mc_cfg)`` — originals are not mutated.
        """
        fraction = self.fte_fraction
        reduction_year = self.year

        # Phase 1: scale gross_salary_eur and pension_accrual_eur
        scaled_flows: list[YearlyFlow] = []
        for flow in proj.flows:
            if flow.entity == self.entity and flow.year >= reduction_year:
                scaled_flows.append(
                    flow.model_copy(
                        update={
                            "gross_salary_eur": (flow.gross_salary_eur * fraction).quantize(
                                _TWO_DP, rounding=ROUND_HALF_EVEN
                            ),
                            "pension_accrual_eur": (flow.pension_accrual_eur * fraction).quantize(
                                _TWO_DP, rounding=ROUND_HALF_EVEN
                            ),
                        }
                    )
                )
            else:
                scaled_flows.append(flow)

        # Phase 2: recompute cumulative_pension_eur for the entity from
        # the reduction year onward (runs in ascending year order).
        flows_sorted = sorted(scaled_flows, key=lambda f: (f.entity, f.year))
        cumulative: dict[str, Decimal] = {}
        final_flows: list[YearlyFlow] = []
        for flow in flows_sorted:
            if flow.entity == self.entity:
                if flow.year < reduction_year:
                    # Pre-reduction: trust the original cumulative
                    cumulative[flow.entity] = flow.cumulative_pension_eur
                    final_flows.append(flow)
                else:
                    # Post-reduction: accumulate from the previous value
                    prev = cumulative.get(flow.entity, Decimal("0"))
                    new_cumulative = (prev + flow.pension_accrual_eur).quantize(
                        _TWO_DP, rounding=ROUND_HALF_EVEN
                    )
                    cumulative[flow.entity] = new_cumulative
                    final_flows.append(
                        flow.model_copy(update={"cumulative_pension_eur": new_cumulative})
                    )
            else:
                final_flows.append(flow)

        # Re-sort to original order (entity-minor, year-major like project())
        final_flows.sort(key=lambda f: (f.year, f.entity))

        new_proj = CashflowProjection(config=proj.config, flows=tuple(final_flows))
        return new_proj, mc_cfg


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

Scenario = HousePurchaseScenario | WorkReductionScenario


class ScenarioResult(BaseModel, frozen=True):
    """Monte-Carlo result for a single (named) scenario."""

    name: str
    mc_result: MonteCarloResult

    def summary_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary dict."""
        return {
            "name": self.name,
            "p_goal_met": str(self.mc_result.p_goal_met),
            "median_fire_year": self.mc_result.median_fire_year,
            "p50_portfolio": {str(yr): str(v) for yr, v in self.mc_result.p50_portfolio.items()},
        }


class ScenarioComparison(BaseModel, frozen=True):
    """Side-by-side comparison of a baseline run against scenarios."""

    baseline: MonteCarloResult
    scenarios: tuple[ScenarioResult, ...]

    def to_json(self) -> str:
        """Serialise the full comparison to JSON."""
        data: dict[str, Any] = {
            "baseline": {
                "p_goal_met": str(self.baseline.p_goal_met),
                "median_fire_year": self.baseline.median_fire_year,
                "p50_portfolio": {str(yr): str(v) for yr, v in self.baseline.p50_portfolio.items()},
            },
            "scenarios": [s.summary_dict() for s in self.scenarios],
        }
        return json.dumps(data, indent=2)

    def to_markdown(self) -> str:
        """Render a markdown comparison table."""
        header = "| Metric | Baseline | " + " | ".join(s.name for s in self.scenarios) + " |"
        sep = "| --- | --- | " + " | ".join("---" for _ in self.scenarios) + " |"
        p_goal = (
            f"| P(goal met) | {self.baseline.p_goal_met} | "
            + " | ".join(str(s.mc_result.p_goal_met) for s in self.scenarios)
            + " |"
        )
        fire_year = (
            f"| Median FIRE year | {self.baseline.median_fire_year or '—'} | "
            + " | ".join(
                str(s.mc_result.median_fire_year) if s.mc_result.median_fire_year else "—"
                for s in self.scenarios
            )
            + " |"
        )
        return "\n".join(["# Scenario Comparison", "", header, sep, p_goal, fire_year])


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class ScenarioError(Exception):
    """Raised when a scenario produces an invalid simulation state."""


def compare(
    cashflow_cfg: CashflowConfig,
    tax_cfg: TaxConfig,
    goal: GoalConfig,
    return_model: BootstrapReturnModel,
    mc_cfg: MonteCarloConfig,
    scenarios: dict[str, Scenario],
) -> ScenarioComparison:
    """Run baseline Monte-Carlo + all scenarios; return a :class:`ScenarioComparison`.

    The baseline cashflow projection is computed once from *cashflow_cfg*.
    Each scenario receives the **same baseline projection** and applies its
    mutations, then runs Monte-Carlo independently.

    The *return_model* is shared (same seed) across all runs so that
    differences in output arise from the scenario mutation, not from RNG
    variance.

    Args:
        cashflow_cfg:
            Baseline cashflow configuration.
        tax_cfg:
            Tax overlay applied to all runs (before Monte-Carlo).
        goal:
            FIRE goal definition.
        return_model:
            Seeded return model — **same instance** for all runs to ensure
            comparability.
        mc_cfg:
            Baseline Monte-Carlo configuration.
        scenarios:
            ``{name: scenario}`` mapping; order is preserved in output.

    Returns:
        :class:`ScenarioComparison` with the baseline result and all
        scenario results.

    Raises:
        ScenarioError:
            If a scenario would produce a negative initial portfolio.
    """
    baseline_proj = project(cashflow_cfg)
    baseline_result = run(baseline_proj, tax_cfg, goal, return_model, mc_cfg)

    scenario_results: list[ScenarioResult] = []
    for name, scen in scenarios.items():
        new_proj, new_mc = scen.apply(baseline_proj, mc_cfg)
        if new_mc.initial_portfolio_eur < Decimal("0"):
            raise ScenarioError(
                f"Scenario '{name}': initial_portfolio_eur would be negative "
                f"({new_mc.initial_portfolio_eur}). Down-payment exceeds the portfolio."
            )
        mc_result = run(new_proj, tax_cfg, goal, return_model, new_mc)
        scenario_results.append(ScenarioResult(name=name, mc_result=mc_result))

    return ScenarioComparison(baseline=baseline_result, scenarios=tuple(scenario_results))
