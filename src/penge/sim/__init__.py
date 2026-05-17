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
- :mod:`penge.sim.household_scenarios` — labelled household scenario presets
  for scenario comparison outputs (issue #170).
- :mod:`penge.sim.stress` — sensitivity and stress-test pack for household plans
  (issue #180).
- :mod:`penge.sim.drawdown` — planning-only tax-aware drawdown-order comparison
  (issue #178).
- :mod:`penge.sim.real_estate` — property and mortgage planning projection
  (issue #185).
- :mod:`penge.sim.household_tax_context` — DK/DE tax-context reporting
  (issue #181).
- :mod:`penge.sim.source_assumptions` — document-backed planning assumption
  extraction with review status (issue #182).
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
from penge.sim.contribution_strategy import (
    ContributionStrategyExplanation,
    ContributionStrategyWarning,
    explain_contribution_strategy,
)
from penge.sim.drawdown import (
    DrawdownAccountKind,
    DrawdownAccountState,
    DrawdownResult,
    DrawdownStrategyDefinition,
    DrawdownYear,
    build_drawdown_accounts,
    compare_drawdown_strategies,
    default_drawdown_strategies,
    evaluate_drawdown_strategy,
)
from penge.sim.goal import (
    GoalConfig,
    GoalResult,
    evaluate,
)
from penge.sim.household_scenarios import (
    DelayedPensionStartPreset,
    HigherInflationPreset,
    HigherMortgageRatePreset,
    HigherSpendingPreset,
    HomePurchasePreset,
    HouseholdScenario,
    HouseholdScenarioPreset,
    HouseholdScenarioPresetName,
    IncreasedSavingsPreset,
    LowerReturnsPreset,
    LowerSavingsPreset,
    OneOffExpensePreset,
    RetireInYearPreset,
    WorkReductionPreset,
    apply_scenario_preset,
    compose_scenario_presets,
)
from penge.sim.household_tax_context import (
    HouseholdTaxContext,
    MemberTaxContext,
    UnsupportedTaxFeature,
    build_household_tax_context,
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
    MortgageConfig,
    PayoutTemplate,
    ProjectionWarning,
    PropertyAssetConfig,
    SpendingYear,
    project_household,
)
from penge.sim.readiness import (
    ReadinessFinding,
    RetirementReadinessReport,
    generate_readiness_report,
)
from penge.sim.real_estate import (
    RealEstateProjection,
    RealEstateYear,
    project_real_estate,
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
from penge.sim.risk import (
    PlanningRiskFinding,
    PlanningRiskRegister,
    generate_risk_register,
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
from penge.sim.source_assumptions import (
    ExtractedPlanningAssumption,
    ParsedPlanningDocument,
    PlanningAssumptionSource,
    accept_planning_assumption,
    accepted_assumptions,
    extract_planning_assumptions,
    reject_planning_assumption,
)
from penge.sim.spending import (
    HouseholdSpendingPlan,
    OneOffExpense,
    SpendingPhase,
    SpendingRule,
    compute_spending,
)
from penge.sim.stress import (
    HouseholdStressResult,
    HouseholdStressTestPack,
    StressTestSpec,
    default_stress_tests,
    run_stress_tests,
)
from penge.sim.tax import (
    DE_DEFAULT,
    DK_DEFAULT,
    EntityTaxRegime,
    TaxConfig,
    apply_tax,
    net_pension_drawdown,
)
from penge.sim.tax_timeline import (
    TaxAttribution,
    TaxTimeline,
    TaxTimelineRow,
    TaxTimelineTotals,
    TaxTimelineWarning,
    build_tax_timeline,
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
    "ContributionStrategyExplanation",
    "ContributionStrategyWarning",
    "DelayedPensionStartPreset",
    "DrawdownAccountKind",
    "DrawdownAccountState",
    "DrawdownResult",
    "DrawdownStrategyDefinition",
    "DrawdownYear",
    "EntityBridgeResult",
    "EntityFolkepensionResult",
    "EntityTaxRegime",
    "ExtractedPlanningAssumption",
    "FolkepensionTemplate",
    "GoalConfig",
    "GoalResult",
    "HigherInflationPreset",
    "HigherMortgageRatePreset",
    "HigherSpendingPreset",
    "HoldingSnapshot",
    "HomePurchasePreset",
    "HousePurchaseScenario",
    "HouseholdBalanceSheet",
    "HouseholdBalanceSheetRow",
    "HouseholdMember",
    "HouseholdPlan",
    "HouseholdProjectionResult",
    "HouseholdScenario",
    "HouseholdScenarioPreset",
    "HouseholdScenarioPresetName",
    "HouseholdSnapshot",
    "HouseholdSpendingPlan",
    "HouseholdStressResult",
    "HouseholdStressTestPack",
    "HouseholdTaxContext",
    "IncreasedSavingsPreset",
    "InstrumentAssumptions",
    "LowerReturnsPreset",
    "LowerSavingsPreset",
    "MemberTaxContext",
    "MonteCarloConfig",
    "MonteCarloResult",
    "MonthlyContributionSplit",
    "MortgageConfig",
    "OneOffExpense",
    "OneOffExpensePreset",
    "ParsedPlanningDocument",
    "PayoutConfig",
    "PayoutError",
    "PayoutProjection",
    "PayoutTemplate",
    "PensionAccrualRule",
    "PlanningAssumptionSource",
    "PlanningRiskFinding",
    "PlanningRiskRegister",
    "ProjectionAuditRecord",
    "ProjectionWarning",
    "PropertyAssetConfig",
    "ReadinessFinding",
    "RealEstateProjection",
    "RealEstateYear",
    "RetireInYearPreset",
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
    "StressTestSpec",
    "TaxAttribution",
    "TaxConfig",
    "TaxRegime",
    "TaxTimeline",
    "TaxTimelineRow",
    "TaxTimelineTotals",
    "TaxTimelineWarning",
    "UnsupportedTaxFeature",
    "WorkReductionPreset",
    "WorkReductionScenario",
    "YearlyContributionSplit",
    "YearlyFlow",
    "accept_planning_assumption",
    "accepted_assumptions",
    "apply_scenario_preset",
    "apply_tax",
    "assess_bridge_spending",
    "build_drawdown_accounts",
    "build_household_tax_context",
    "build_standard_audit_record",
    "build_tax_timeline",
    "compare",
    "compare_configs",
    "compare_drawdown_strategies",
    "compose_scenario_presets",
    "compute_payout",
    "compute_spending",
    "default_drawdown_strategies",
    "default_stress_tests",
    "evaluate",
    "evaluate_drawdown_strategy",
    "explain_contribution_strategy",
    "extract_planning_assumptions",
    "first_liquidity_depletion",
    "generate_readiness_report",
    "generate_risk_register",
    "net_pension_drawdown",
    "project",
    "project_balance_sheet",
    "project_household",
    "project_real_estate",
    "reject_planning_assumption",
    "required_starting_capital_for_bridge_spending",
    "route_contributions",
    "run",
    "run_stress_tests",
    "simulate_routing",
    "simulate_routing_monthly",
    "summarize_bridge_result",
]
