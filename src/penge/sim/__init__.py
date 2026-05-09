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

Future modules planned for milestone M2 (FIRE & Scenarios):

- ``penge.sim.scenario`` — scenario diff engine (#32).
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
from penge.sim.returns import (
    BootstrapReturnModel,
    ReturnModelError,
    SampledPaths,
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
    "ContributionRule",
    "EntityTaxRegime",
    "GoalConfig",
    "GoalResult",
    "MonteCarloConfig",
    "MonteCarloResult",
    "PensionAccrualRule",
    "ReturnModelError",
    "SalaryRule",
    "SampledPaths",
    "TaxConfig",
    "YearlyFlow",
    "apply_tax",
    "evaluate",
    "net_pension_drawdown",
    "project",
    "run",
]
