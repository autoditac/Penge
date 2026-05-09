"""Penge simulation package.

Subpackages:

- :mod:`penge.sim.returns` — historical block-bootstrap return / inflation
  model (issue #26, ADR-0010).
- :mod:`penge.sim.cashflow` — deterministic cashflow engine (issue #27,
  ADR-0011).
- :mod:`penge.sim.goal` — FIRE goal evaluation engine (issue #30,
  ADR-0012).

Future modules planned for milestone M2 (FIRE & Scenarios):

- ``penge.sim.tax`` — statutory tax rates per regime (#28).
- ``penge.sim.montecarlo`` — vectorized Monte-Carlo runner (#31).
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
from penge.sim.returns import (
    BootstrapReturnModel,
    ReturnModelError,
    SampledPaths,
)

__all__ = [
    "BootstrapReturnModel",
    "CashflowConfig",
    "CashflowError",
    "CashflowProjection",
    "ContributionRule",
    "GoalConfig",
    "GoalResult",
    "PensionAccrualRule",
    "ReturnModelError",
    "SalaryRule",
    "SampledPaths",
    "YearlyFlow",
    "evaluate",
    "project",
]
