"""Explanation-first household planning surface for MCP/dashboard consumers."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal

import pydantic

from penge.sim.balance import HouseholdBalanceSheetRow
from penge.sim.cashflow import PensionAccrualRule, SalaryRule
from penge.sim.liquid import LiquidDepotConfig
from penge.sim.plan import (
    BridgeTemplate,
    FolkepensionTemplate,
    HouseholdMember,
    HouseholdPlan,
    HouseholdProjectionResult,
    PayoutTemplate,
    project_household,
)
from penge.sim.readiness import RetirementReadinessReport, generate_readiness_report
from penge.sim.registry import AssumptionEntry
from penge.sim.spending import HouseholdSpendingPlan, SpendingRule
from penge.sim.stress import HouseholdStressTestPack, run_stress_tests
from penge.sim.tax import DE_DEFAULT, DK_DEFAULT, TaxConfig

__all__ = [
    "PlanningAnswer",
    "PlanningAssumptionSummary",
    "PlanningEvidence",
    "PlanningLimitation",
    "PlanningRiskSummary",
    "PlanningSurfaceReport",
    "PlanningSurfaceRequest",
    "QuestionId",
    "build_synthetic_household_plan",
    "generate_planning_surface",
]

QuestionId = Literal[
    "can_we_retire",
    "what_breaks_first",
    "how_do_taxes_affect_plan",
    "which_assumptions_matter",
    "which_scenarios_should_we_test",
]
PlanId = Literal["synthetic_household"]
AnswerStatus = Literal["ready", "watch", "not_ready", "info"]

DEFAULT_QUESTION_IDS: tuple[QuestionId, ...] = (
    "can_we_retire",
    "what_breaks_first",
    "how_do_taxes_affect_plan",
)
_TWO_DP = Decimal("0.01")
_DOC_LINKS: tuple[str, ...] = (
    "docs/sim/personas.md",
    "docs/sim/planning-outputs.md",
    "docs/tax/dk.md",
    "docs/tax/de.md",
    "docs/decisions/0032-household-real-estate-tax-context-source-assumptions.md",
)
_TAX_CONTEXT_RISK_CODES: frozenset[str] = frozenset(
    {
        "topskat_exposure",
        "material_tax_drag_change",
        "folkepension_tillaeg_fully_reduced",
        "folkepension_reduced",
        "de_vorabpauschale_not_in_household_plan",
        "de_income_tax_brackets_not_modelled",
    }
)


class PlanningSurfaceError(ValueError):
    """Raised when a planning surface cannot be generated."""


class PlanningEvidence(pydantic.BaseModel):
    """One labelled data point supporting a planning answer."""

    model_config = pydantic.ConfigDict(frozen=True)

    label: str
    value: str
    source: str


class PlanningRiskSummary(pydantic.BaseModel):
    """Risk finding exposed to MCP hosts without raw projection internals."""

    model_config = pydantic.ConfigDict(frozen=True)

    code: str
    severity: Literal["info", "warning", "critical"]
    message: str
    affected_year: int | None
    source_assumption: str
    next_action: str


class PlanningAssumptionSummary(pydantic.BaseModel):
    """Named planning assumption linked from answers."""

    model_config = pydantic.ConfigDict(frozen=True)

    key: str
    value: str
    unit: str
    source: str
    notes: str = ""


class PlanningLimitation(pydantic.BaseModel):
    """Visible model or data-boundary limitation."""

    model_config = pydantic.ConfigDict(frozen=True)

    code: str
    message: str
    docs: tuple[str, ...]


class PlanningAnswer(pydantic.BaseModel):
    """Direct answer to one household planning question."""

    model_config = pydantic.ConfigDict(frozen=True)

    question_id: QuestionId
    question: str
    status: AnswerStatus
    answer: str
    evidence: tuple[PlanningEvidence, ...]
    risk_codes: tuple[str, ...]
    assumption_keys: tuple[str, ...]
    limitation_codes: tuple[str, ...]
    docs: tuple[str, ...]


class PlanningSurfaceReport(pydantic.BaseModel):
    """Structured planning dashboard/report payload for MCP tools."""

    model_config = pydantic.ConfigDict(frozen=True)

    plan_id: PlanId
    surface: Literal["household_planning_questions"]
    generated_by: Literal["penge.sim.planning_surface"]
    overall_status: AnswerStatus
    questions: tuple[PlanningAnswer, ...]
    risks: tuple[PlanningRiskSummary, ...]
    assumptions: tuple[PlanningAssumptionSummary, ...]
    limitations: tuple[PlanningLimitation, ...]
    docs: tuple[str, ...]


class PlanningSurfaceRequest(pydantic.BaseModel):
    """Request for the deterministic household planning surface."""

    model_config = pydantic.ConfigDict(frozen=True)

    plan_id: PlanId = "synthetic_household"
    questions: tuple[QuestionId, ...] = DEFAULT_QUESTION_IDS

    @pydantic.field_validator("questions")
    @classmethod
    def _validate_questions(cls, value: tuple[QuestionId, ...]) -> tuple[QuestionId, ...]:
        if not value:
            raise ValueError("questions must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("questions must be unique")
        return value


def build_synthetic_household_plan() -> HouseholdPlan:
    """Return a fully synthetic DK/DE household plan for MCP demos and tests."""

    return HouseholdPlan(
        base_year=2024,
        horizon_years=12,
        inflation_rate=Decimal("0.02"),
        eur_per_dkk=Decimal("0.134"),
        pension_market_return_rate=Decimal("0.04"),
        pal_skat_rate=Decimal("0.153"),
        members=(
            HouseholdMember(
                name="alice",
                birth_year=1980,
                jurisdiction="DK",
                tax_country="DK",
                retirement_year=2028,
                public_pension_start_year=2035,
            ),
            HouseholdMember(
                name="bob",
                birth_year=1982,
                jurisdiction="DE",
                tax_country="DE",
                retirement_year=2029,
                public_pension_start_year=2038,
            ),
        ),
        salaries=(SalaryRule(entity="alice", gross_annual=Decimal("100000")),),
        pension_rules=(
            PensionAccrualRule(
                entity="alice",
                kind="annual_eur",
                annual_eur=Decimal("12000"),
                vesting_year=2035,
            ),
        ),
        pension_opening_balances={"alice": Decimal("1000000"), "bob": Decimal("250000")},
        tax_config=TaxConfig(regimes={"alice": DK_DEFAULT, "bob": DE_DEFAULT}),
        spending_plan=HouseholdSpendingPlan(
            rules=(
                SpendingRule(
                    label="living",
                    annual_amount=Decimal("300000"),
                    currency="DKK",
                    inflation_rate=Decimal("0"),
                ),
            )
        ),
        liquid_configs=(
            LiquidDepotConfig(
                account_id="alice-ask",
                account_type="ask",
                tax_regime="lager",
                opening_balance_dkk=Decimal("900000"),
                ask_lifetime_deposits_dkk=Decimal("100000"),
                annual_contribution_dkk=Decimal("20000"),
                gross_annual_return_rate=Decimal("0.05"),
                annual_expense_ratio=Decimal("0.005"),
                tax_source="depot",
                aktieindkomst_threshold_dkk=Decimal("67500"),
            ),
            LiquidDepotConfig(
                account_id="alice-frie",
                account_type="frie_midler",
                tax_regime="realisation",
                opening_balance_dkk=Decimal("300000"),
                annual_contribution_dkk=Decimal("10000"),
                gross_annual_return_rate=Decimal("0.06"),
                annual_expense_ratio=Decimal("0.005"),
                annual_dividend_yield=Decimal("0.03"),
                tax_source="external",
                aktieindkomst_threshold_dkk=Decimal("67500"),
                opening_cost_basis_dkk=Decimal("250000"),
            ),
        ),
        bridge_templates=(
            BridgeTemplate(
                entity="alice",
                liquid_account_id="alice-frie",
                bridge_start_year=2028,
                horizon_months=72,
                gross_annual_return_rate=Decimal("0.04"),
                annual_expense_ratio=Decimal("0.005"),
                account_type="frie_midler",
                tax_regime="realisation",
                aktieindkomst_threshold_dkk=Decimal("67500"),
                annual_dividend_yield=Decimal("0.03"),
            ),
        ),
        payout_templates=(
            PayoutTemplate(
                entity="alice",
                retirement_year=2028,
                retirement_age=65,
                livrente_fraction=Decimal("0.70"),
                ratepension_fraction=Decimal("0.25"),
                ratepension_years=15,
                annuity_factor=Decimal("4800"),
            ),
        ),
        folkepension_templates=(FolkepensionTemplate(entity="alice", civil_status="married"),),
    )


def generate_planning_surface(
    request: PlanningSurfaceRequest | None = None,
    *,
    plan: HouseholdPlan | None = None,
) -> PlanningSurfaceReport:
    """Generate a direct-answer planning surface from one household plan.

    Args:
        request: Plan id and question ids requested by the MCP client.
        plan: Optional already-built plan, mainly for tests. When omitted,
            ``request.plan_id == "synthetic_household"`` uses the built-in
            synthetic household plan.
    """

    req = request or PlanningSurfaceRequest()
    active_plan = plan if plan is not None else build_synthetic_household_plan()
    projection = project_household(active_plan)
    readiness = generate_readiness_report(projection)
    stress = run_stress_tests(active_plan)
    risks = _risk_summaries(readiness)
    assumptions = _assumption_summaries(projection, readiness)
    limitations = _limitations(readiness)
    answers = tuple(
        _build_answer(question, readiness, projection, stress, assumptions, limitations)
        for question in req.questions
    )
    return PlanningSurfaceReport(
        plan_id=req.plan_id,
        surface="household_planning_questions",
        generated_by="penge.sim.planning_surface",
        overall_status=readiness.conclusion,
        questions=answers,
        risks=risks,
        assumptions=assumptions,
        limitations=limitations,
        docs=_DOC_LINKS,
    )


def _build_answer(
    question: QuestionId,
    readiness: RetirementReadinessReport,
    projection: HouseholdProjectionResult,
    stress: HouseholdStressTestPack,
    assumptions: tuple[PlanningAssumptionSummary, ...],
    limitations: tuple[PlanningLimitation, ...],
) -> PlanningAnswer:
    if question == "can_we_retire":
        return _answer_can_we_retire(readiness)
    if question == "what_breaks_first":
        return _answer_what_breaks_first(readiness)
    if question == "how_do_taxes_affect_plan":
        return _answer_tax(readiness)
    if question == "which_assumptions_matter":
        return _answer_assumptions(projection, assumptions, limitations)
    if question == "which_scenarios_should_we_test":
        return _answer_scenarios(stress)
    raise PlanningSurfaceError(f"unsupported planning question: {question}")


def _answer_can_we_retire(readiness: RetirementReadinessReport) -> PlanningAnswer:
    terminal = readiness.balance_sheet.rows[-1]
    material_risks = _material_risks(readiness)
    risk_codes = tuple(finding.code for finding in material_risks[:5])
    return PlanningAnswer(
        question_id="can_we_retire",
        question="Can this household retire on the planned timeline?",
        status=readiness.conclusion,
        answer=(
            f"The plan is {readiness.conclusion} for retirement in "
            f"{readiness.planned_retirement_year}. "
            f"Terminal spendable liquidity is {_fmt_money(terminal.spendable_liquidity_dkk)} "
            f"and terminal net worth is {_fmt_money(terminal.total_net_worth_dkk)}. "
            "Review the linked risks before treating this as a decision."
        ),
        evidence=(
            PlanningEvidence(
                label="planned_retirement_year",
                value=str(readiness.planned_retirement_year),
                source="RetirementReadinessReport",
            ),
            _balance_evidence("terminal_spendable_liquidity_dkk", terminal),
            _balance_evidence("terminal_total_net_worth_dkk", terminal),
        ),
        risk_codes=risk_codes,
        assumption_keys=(
            "planned_retirement_year",
            "annual_spending_plan",
            "eur_per_dkk",
            "liquid_depot_projection",
            "bridge_templates",
        ),
        limitation_codes=("planning_grade_not_filing_advice",),
        docs=("docs/sim/planning-outputs.md", "docs/sim/personas.md"),
    )


def _answer_what_breaks_first(readiness: RetirementReadinessReport) -> PlanningAnswer:
    material_risks = _material_risks(readiness)
    if not material_risks:
        return PlanningAnswer(
            question_id="what_breaks_first",
            question="What breaks first if the plan fails?",
            status="ready",
            answer="No material risk finding is present in the generated risk register.",
            evidence=(
                PlanningEvidence(
                    label="risk_register",
                    value="no_material_risks",
                    source="PlanningRiskRegister",
                ),
            ),
            risk_codes=(),
            assumption_keys=("risk_register_generation",),
            limitation_codes=("planning_grade_not_filing_advice",),
            docs=("docs/sim/planning-outputs.md",),
        )
    first = sorted(material_risks, key=lambda item: (item.affected_year or 9999, item.code))[0]
    status: AnswerStatus = "not_ready" if first.severity == "critical" else "watch"
    year = "unknown year" if first.affected_year is None else str(first.affected_year)
    return PlanningAnswer(
        question_id="what_breaks_first",
        question="What breaks first if the plan fails?",
        status=status,
        answer=(
            f"The first material issue is `{first.code}` in {year}: "
            f"{first.message} Next action: {first.next_action}"
        ),
        evidence=(
            PlanningEvidence(label="risk_code", value=first.code, source="PlanningRiskRegister"),
            PlanningEvidence(label="affected_year", value=year, source="PlanningRiskRegister"),
        ),
        risk_codes=(first.code,),
        assumption_keys=(_assumption_key_for_source(first.source_assumption),),
        limitation_codes=("planning_grade_not_filing_advice",),
        docs=("docs/sim/planning-outputs.md",),
    )


def _answer_tax(readiness: RetirementReadinessReport) -> PlanningAnswer:
    tax_context_risks = tuple(
        finding.code
        for finding in readiness.risk_register.findings
        if finding.code in _TAX_CONTEXT_RISK_CODES
    )
    return PlanningAnswer(
        question_id="how_do_taxes_affect_plan",
        question="How do taxes affect this plan?",
        status="watch" if tax_context_risks else "info",
        answer=(
            "The planning report estimates "
            f"{_fmt_money(readiness.total_liquid_tax_dkk)} liquid-depot tax, "
            f"{_fmt_money(readiness.total_bridge_tax_dkk)} bridge tax, and "
            f"{_fmt_money(readiness.tax_timeline.totals.total_tax_drag_dkk)} total timeline "
            "tax drag. DK/DE limitations are surfaced as linked risks where relevant."
        ),
        evidence=(
            PlanningEvidence(
                label="liquid_depot_tax_dkk",
                value=_fmt_money(readiness.total_liquid_tax_dkk),
                source="RetirementReadinessReport",
            ),
            PlanningEvidence(
                label="bridge_tax_dkk",
                value=_fmt_money(readiness.total_bridge_tax_dkk),
                source="RetirementReadinessReport",
            ),
            PlanningEvidence(
                label="total_timeline_tax_drag_dkk",
                value=_fmt_money(readiness.tax_timeline.totals.total_tax_drag_dkk),
                source="TaxTimeline",
            ),
        ),
        risk_codes=tax_context_risks[:5],
        assumption_keys=("tax_config", "household_tax_context"),
        limitation_codes=("planning_grade_not_filing_advice",),
        docs=("docs/tax/dk.md", "docs/tax/de.md", "docs/sim/planning-outputs.md"),
    )


def _answer_assumptions(
    projection: HouseholdProjectionResult,
    assumptions: tuple[PlanningAssumptionSummary, ...],
    limitations: tuple[PlanningLimitation, ...],
) -> PlanningAnswer:
    keys = tuple(item.key for item in assumptions[:6])
    limitation_codes = tuple(item.code for item in limitations)
    return PlanningAnswer(
        question_id="which_assumptions_matter",
        question="Which assumptions should be reviewed before deciding?",
        status="watch",
        answer=(
            "Review retirement timing, annual spending, EUR/DKK FX, tax-country context, "
            "liquid-depot return/tax constants, and any source-backed assumptions before "
            "using the report. The surface links each answer to assumption keys rather "
            "than hiding them in prose."
        ),
        evidence=(
            PlanningEvidence(
                label="audit_assumptions",
                value=str(len(projection.audit_record.assumptions)),
                source="ProjectionAuditRecord",
            ),
            PlanningEvidence(
                label="linked_assumption_keys",
                value=", ".join(keys),
                source="PlanningSurfaceReport.assumptions",
            ),
        ),
        risk_codes=(),
        assumption_keys=keys,
        limitation_codes=limitation_codes,
        docs=(
            "docs/sim/registry.md",
            "docs/sim/assumptions.md",
            "docs/decisions/0032-household-real-estate-tax-context-source-assumptions.md",
        ),
    )


def _answer_scenarios(stress: HouseholdStressTestPack) -> PlanningAnswer:
    top_results = stress.results[:3]
    scenario_labels = ", ".join(
        f"{item.rank}. {item.label} ({_fmt_money(item.impact_score_dkk)} impact score)"
        for item in top_results
    )
    changed_assumptions = tuple(
        assumption for result in top_results for assumption in result.changed_assumptions[:2]
    )
    return PlanningAnswer(
        question_id="which_scenarios_should_we_test",
        question="Which scenarios should we test before deciding?",
        status="info",
        answer=(f"Start with the highest-impact deterministic stress tests: {scenario_labels}."),
        evidence=tuple(
            PlanningEvidence(
                label=f"stress_rank_{item.rank}",
                value=f"{item.name}: {_fmt_money(item.impact_score_dkk)}",
                source="HouseholdStressTestPack",
            )
            for item in top_results
        ),
        risk_codes=(),
        assumption_keys=changed_assumptions,
        limitation_codes=("planning_grade_not_filing_advice",),
        docs=("docs/sim/planning-outputs.md",),
    )


def _risk_summaries(readiness: RetirementReadinessReport) -> tuple[PlanningRiskSummary, ...]:
    return tuple(
        PlanningRiskSummary(
            code=finding.code,
            severity=finding.severity,
            message=finding.message,
            affected_year=finding.affected_year,
            source_assumption=finding.source_assumption,
            next_action=finding.next_action,
        )
        for finding in readiness.risk_register.findings
    )


def _assumption_summaries(
    projection: HouseholdProjectionResult,
    readiness: RetirementReadinessReport,
) -> tuple[PlanningAssumptionSummary, ...]:
    plan = projection.plan
    custom = [
        PlanningAssumptionSummary(
            key="planned_retirement_year",
            value=str(readiness.planned_retirement_year),
            unit="year",
            source="HouseholdPlan.members",
        ),
        PlanningAssumptionSummary(
            key="annual_spending_plan",
            value=_fmt_money(readiness.balance_sheet.rows[0].annual_spending_dkk),
            unit="DKK/year",
            source="HouseholdSpendingPlan",
        ),
        PlanningAssumptionSummary(
            key="eur_per_dkk",
            value=str(plan.eur_per_dkk),
            unit="EUR per DKK",
            source="ECB FX assumption",
        ),
        PlanningAssumptionSummary(
            key="household_tax_context",
            value=", ".join(
                f"{member.name}:{member.effective_tax_country}" for member in plan.members
            ),
            unit="tax country",
            source="HouseholdMember.tax_country",
        ),
        PlanningAssumptionSummary(
            key="tax_config",
            value=", ".join(plan.tax_config.regimes.keys()),
            unit="entity regimes",
            source="TaxConfig",
        ),
        PlanningAssumptionSummary(
            key="liquid_depot_projection",
            value=str(len(plan.liquid_configs)),
            unit="accounts",
            source="HouseholdPlan.liquid_configs",
        ),
        PlanningAssumptionSummary(
            key="bridge_templates",
            value=str(len(plan.bridge_templates)),
            unit="templates",
            source="HouseholdPlan.bridge_templates",
        ),
        PlanningAssumptionSummary(
            key="risk_register_generation",
            value=str(len(readiness.risk_register.findings)),
            unit="findings",
            source="PlanningRiskRegister",
        ),
    ]
    audit_entries = tuple(
        _audit_assumption_summary(entry) for entry in projection.audit_record.assumptions
    )
    return tuple(custom) + audit_entries[:12]


def _audit_assumption_summary(entry: AssumptionEntry) -> PlanningAssumptionSummary:
    return PlanningAssumptionSummary(
        key=entry.name,
        value=entry.value,
        unit=entry.unit,
        source=entry.source,
        notes=entry.notes,
    )


def _assumption_key_for_source(source_assumption: str) -> str:
    if "household tax context" in source_assumption.lower():
        return "household_tax_context"
    if "TaxConfig" in source_assumption or "tax" in source_assumption.lower():
        return "tax_config"
    if "spending" in source_assumption.lower():
        return "annual_spending_plan"
    if "bridge" in source_assumption.lower():
        return "bridge_templates"
    if "retirement" in source_assumption.lower():
        return "planned_retirement_year"
    return "risk_register_generation"


def _limitations(readiness: RetirementReadinessReport) -> tuple[PlanningLimitation, ...]:
    items = [
        PlanningLimitation(
            code="planning_grade_not_filing_advice",
            message=(
                "Household planning outputs are decision-support estimates, not filing-grade "
                "tax calculations or investment advice."
            ),
            docs=("docs/sim/planning-outputs.md", "docs/tax/dk.md", "docs/tax/de.md"),
        ),
        PlanningLimitation(
            code="source_assumptions_require_acceptance",
            message=(
                "Document-extracted assumptions remain suggestions until explicitly accepted "
                "by a reviewer."
            ),
            docs=(
                "docs/sim/planning-outputs.md",
                "docs/decisions/0032-household-real-estate-tax-context-source-assumptions.md",
            ),
        ),
        PlanningLimitation(
            code="mcp_returns_summary_not_raw_documents",
            message="MCP planning answers return summaries and references, not raw document text.",
            docs=("docs/mcp/tools.md", "docs/privacy.md"),
        ),
    ]
    for unsupported in readiness.tax_context.unsupported_features:
        items.append(
            PlanningLimitation(
                code=unsupported.code,
                message=f"{unsupported.member}: {unsupported.description}",
                docs=("docs/tax/de.md", "docs/sim/planning-outputs.md"),
            )
        )
    return tuple(items)


def _material_risks(readiness: RetirementReadinessReport) -> tuple[PlanningRiskSummary, ...]:
    return tuple(
        risk for risk in _risk_summaries(readiness) if risk.severity in {"warning", "critical"}
    )


def _balance_evidence(label: str, row: HouseholdBalanceSheetRow) -> PlanningEvidence:
    value = row.spendable_liquidity_dkk if "spendable" in label else row.total_net_worth_dkk
    return PlanningEvidence(label=label, value=_fmt_money(value), source="HouseholdBalanceSheet")


def _fmt_money(value: Decimal) -> str:
    return f"{value.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN):,} DKK"
