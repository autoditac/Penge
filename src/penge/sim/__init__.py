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
- :mod:`penge.sim.assumptions` — investment assumption catalog for
  instruments and accounts (issue #177).
- :mod:`penge.sim.registry` — assumption registry and projection audit record
  (issue #173).
- :mod:`penge.sim.snapshot` — household planning snapshot from ingested
  accounts (issue #176).
- :mod:`penge.sim.spending` — household spending and target-expense model
  (issue #174).
- :mod:`penge.sim.plan` — household plan orchestrator: end-to-end projection
  runner (issue #167, ADR-0031).
"""

from penge.sim.assumptions import (
    AssumptionCatalog,
    InstrumentAssumptions,
    TaxRegime,
)
from penge.sim.balance import (
    HouseholdBalanceSheet,
    HouseholdBalanceSheetRow,
    first_liquidity_depletion,
    project_balance_sheet,
)
from penge.sim.bridge_spending import (
    BridgeSafeSpendingResult,
    assess_bridge_spending,
    required_starting_capital_for_bridge_spending,
    summarize_bridge_result,
)
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
from penge.sim.plan import (
    BridgeTemplate,
    EntityBridgeResult,
    EntityFolkepensionResult,
    FolkepensionTemplate,
    HouseholdMember,
    HouseholdPlan,
    HouseholdProjectionResult,
    PayoutTemplate,
    ProjectionWarning,
    SpendingYear,
    project_household,
)
from penge.sim.readiness import (
    ReadinessFinding,
    RetirementReadinessReport,
    generate_readiness_report,
)
from penge.sim.registry import (
    AssumptionEntry,
    ProjectionAuditRecord,
    build_standard_audit_record,
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
from penge.sim.snapshot import (
    AccountKind,
    AccountSnapshot,
    HoldingSnapshot,
    HouseholdSnapshot,
    SnapshotBuilder,
)
from penge.sim.spending import (
    HouseholdSpendingPlan,
    OneOffExpense,
    SpendingPhase,
    SpendingRule,
    compute_spending,
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
    "AccountKind",
    "AccountSnapshot",
    "AssumptionCatalog",
    "AssumptionEntry",
    "BootstrapReturnModel",
    "BridgeSafeSpendingResult",
    "BridgeTemplate",
    "CashflowConfig",
    "CashflowError",
    "CashflowProjection",
    "ConfigCompareError",
    "ConfigComparison",
    "ConfigComparisonResult",
    "ContributionRouter",
    "ContributionRoutingError",
    "ContributionRule",
    "EntityBridgeResult",
    "EntityFolkepensionResult",
    "EntityTaxRegime",
    "FolkepensionTemplate",
    "GoalConfig",
    "GoalResult",
    "HoldingSnapshot",
    "HousePurchaseScenario",
    "HouseholdBalanceSheet",
    "HouseholdBalanceSheetRow",
    "HouseholdMember",
    "HouseholdPlan",
    "HouseholdProjectionResult",
    "HouseholdSnapshot",
    "HouseholdSpendingPlan",
    "InstrumentAssumptions",
    "MonteCarloConfig",
    "MonteCarloResult",
    "MonthlyContributionSplit",
    "OneOffExpense",
    "PayoutConfig",
    "PayoutError",
    "PayoutProjection",
    "PayoutTemplate",
    "PensionAccrualRule",
    "ProjectionAuditRecord",
    "ProjectionWarning",
    "ReadinessFinding",
    "RetirementReadinessReport",
    "ReturnModelError",
    "SalaryRule",
    "SampledPaths",
    "ScenarioComparison",
    "ScenarioError",
    "ScenarioResult",
    "SnapshotBuilder",
    "SpendingPhase",
    "SpendingRule",
    "SpendingYear",
    "TaxConfig",
    "TaxRegime",
    "WorkReductionScenario",
    "YearlyContributionSplit",
    "YearlyFlow",
    "apply_tax",
    "assess_bridge_spending",
    "build_standard_audit_record",
    "compare",
    "compare_configs",
    "compute_payout",
    "compute_spending",
    "evaluate",
    "first_liquidity_depletion",
    "generate_readiness_report",
    "net_pension_drawdown",
    "project",
    "project_balance_sheet",
    "project_household",
    "required_starting_capital_for_bridge_spending",
    "route_contributions",
    "run",
    "simulate_routing",
    "simulate_routing_monthly",
    "summarize_bridge_result",
]
