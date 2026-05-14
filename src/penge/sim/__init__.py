"""Penge simulation package.

Subpackages:

- :mod:`penge.sim.returns` — historical block-bootstrap return / inflation
  model (issue #26, ADR-0010).
- :mod:`penge.sim.cashflow` — deterministic cashflow engine (issue #27,
  ADR-0011).
- :mod:`penge.sim.goal` — FIRE goal evaluation engine (issue #30,
  ADR-0012).
- :mod:`penge.sim.tax` — statutory tax overlay (issue #28, ADR-0013).
- :mod:`penge.sim.montecarlo` — vectorized Monte-Carlo runner (issue #31, ADR-0014).
- :mod:`penge.sim.scenario` — scenario diff engine (issue #32, ADR-0015).
- :mod:`penge.sim.config_compare` — side-by-side comparison of N labelled
  ``CashflowConfig`` projections (issue #127).
- :mod:`penge.sim.payout` — decumulation payout model: Livrente + Ratepension
  + Aldersforsikring (issue #132, ADR-0028).
"""

from penge.sim.cashflow import (
    CashflowConfig,
    CashflowError,
    CashflowProjection,
    ContributionRule,
    PensionAccrualRule,
    SalaryRule,
    YearlyFlow,
    project,
)
from penge.sim.config_compare import (
    ConfigCompareError,
    ConfigComparison,
    ConfigComparisonResult,
    compare_configs,
)
from penge.sim.goal import (
    GoalConfig,
    GoalResult,
    evaluate,
)
from penge.sim.montecarlo import (
    MonteCarloConfig,
    MonteCarloResult,
    run,
)
from penge.sim.payout import (
    PayoutConfig,
    PayoutError,
    PayoutProjection,
    compute_payout,
)
from penge.sim.returns import (
    BootstrapReturnModel,
    ReturnModelError,
    SampledPaths,
)
from penge.sim.routing import (
    ContributionRouter,
    ContributionRoutingError,
    MonthlyContributionSplit,
    YearlyContributionSplit,
    route_contributions,
    simulate_routing,
    simulate_routing_monthly,
)
from penge.sim.scenario import (
    HousePurchaseScenario,
    ScenarioComparison,
    ScenarioError,
    ScenarioResult,
    WorkReductionScenario,
    compare,
)
from penge.sim.tax import (
    DE_DEFAULT,
    DK_DEFAULT,
    EntityTaxRegime,
    TaxConfig,
    apply_tax,
    net_pension_drawdown,
)

__all__ = [
    "DE_DEFAULT",
    "DK_DEFAULT",
    "BootstrapReturnModel",
    "CashflowConfig",
    "CashflowError",
    "CashflowProjection",
    "ConfigCompareError",
    "ConfigComparison",
    "ConfigComparisonResult",
    "ContributionRouter",
    "ContributionRoutingError",
    "ContributionRule",
    "EntityTaxRegime",
    "GoalConfig",
    "GoalResult",
    "HousePurchaseScenario",
    "MonteCarloConfig",
    "MonteCarloResult",
    "MonthlyContributionSplit",
    "PayoutConfig",
    "PayoutError",
    "PayoutProjection",
    "PensionAccrualRule",
    "ReturnModelError",
    "SalaryRule",
    "SampledPaths",
    "ScenarioComparison",
    "ScenarioError",
    "ScenarioResult",
    "TaxConfig",
    "WorkReductionScenario",
    "YearlyContributionSplit",
    "YearlyFlow",
    "apply_tax",
    "compare",
    "compare_configs",
    "compute_payout",
    "evaluate",
    "net_pension_drawdown",
    "project",
    "route_contributions",
    "run",
    "simulate_routing",
    "simulate_routing_monthly",
]
