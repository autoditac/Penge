"""Planning risk register for household projections."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

import pydantic

from penge.sim.balance import HouseholdBalanceSheet, project_balance_sheet
from penge.sim.contribution_strategy import ContributionStrategyExplanation
from penge.sim.plan import HouseholdProjectionResult
from penge.sim.tax_timeline import TaxTimeline, build_tax_timeline

__all__ = [
    "PlanningRiskFinding",
    "PlanningRiskRegister",
    "generate_risk_register",
]


class PlanningRiskFinding(pydantic.BaseModel):
    """Named planning risk finding."""

    model_config = pydantic.ConfigDict(frozen=True)

    code: str
    severity: Literal["info", "warning", "critical"]
    message: str
    affected_year: int | None = None
    source_assumption: str
    next_action: str


class PlanningRiskRegister(pydantic.BaseModel):
    """Risk register generated from household planning outputs."""

    model_config = pydantic.ConfigDict(frozen=True)

    findings: tuple[PlanningRiskFinding, ...]


def generate_risk_register(
    result: HouseholdProjectionResult,
    *,
    tax_timeline: TaxTimeline | None = None,
    balance_sheet: HouseholdBalanceSheet | None = None,
    contribution_strategy: ContributionStrategyExplanation | None = None,
) -> PlanningRiskRegister:
    """Generate named planning risk findings from projection outputs."""

    timeline = tax_timeline if tax_timeline is not None else build_tax_timeline(result)
    balances = balance_sheet if balance_sheet is not None else project_balance_sheet(result)
    findings: list[PlanningRiskFinding] = []
    _append_liquidity_findings(findings, balances, result)
    _append_tax_findings(findings, timeline)
    _append_folkepension_findings(findings, result)
    _append_ask_findings(findings, result, contribution_strategy)
    _append_projection_warning_findings(findings, result)
    if not findings:
        findings.append(
            PlanningRiskFinding(
                code="no_material_risks",
                severity="info",
                message="No material planning risks were detected.",
                source_assumption="HouseholdProjectionResult",
                next_action="Review assumptions periodically.",
            )
        )
    return PlanningRiskRegister(findings=tuple(findings))


def _append_liquidity_findings(
    findings: list[PlanningRiskFinding],
    balances: HouseholdBalanceSheet,
    result: HouseholdProjectionResult,
) -> None:
    public_pension_years = [
        member.public_pension_start_year
        for member in result.plan.members
        if member.public_pension_start_year is not None
    ]
    first_public_pension_year = min(public_pension_years) if public_pension_years else None
    for row in balances.rows:
        if not row.liquidity_depleted:
            continue
        findings.append(
            PlanningRiskFinding(
                code="liquidity_depleted",
                severity="critical",
                affected_year=row.year,
                message="Spendable liquidity is depleted while planned spending remains positive.",
                source_assumption="Household spending plan and liquid account balances",
                next_action="Reduce spending, retire later, or add spendable bridge capital.",
            )
        )
        if row.locked_pension_dkk > Decimal("0") and (
            first_public_pension_year is None or row.year < first_public_pension_year
        ):
            findings.append(
                PlanningRiskFinding(
                    code="locked_pension_before_access",
                    severity="critical",
                    affected_year=row.year,
                    message=(
                        "Plan has locked pension wealth but no spendable liquidity "
                        "before pension access."
                    ),
                    source_assumption="Pension opening balances and public pension start years",
                    next_action="Increase liquid savings or model a later retirement date.",
                )
            )
        break


def _append_tax_findings(
    findings: list[PlanningRiskFinding],
    timeline: TaxTimeline,
) -> None:
    for row in timeline.rows:
        if row.topskat_exposure_dkk > Decimal("0"):
            findings.append(
                PlanningRiskFinding(
                    code="topskat_exposure",
                    severity="warning",
                    affected_year=row.year,
                    message=(
                        f"DK income exceeds Topskat threshold by {row.topskat_exposure_dkk} DKK."
                    ),
                    source_assumption="DK_TOPSKAT_THRESHOLD_DKK",
                    next_action="Review salary/pension drawdown timing and DK tax assumptions.",
                )
            )
            break
    material_change = next(
        (warning for warning in timeline.warnings if warning.code == "material_tax_drag_change"),
        None,
    )
    if material_change is not None:
        findings.append(
            PlanningRiskFinding(
                code="material_tax_drag_change",
                severity="warning",
                affected_year=material_change.year,
                message=material_change.message,
                source_assumption="TaxTimeline.total_tax_drag_dkk",
                next_action="Inspect the tax event timeline around this year.",
            )
        )


def _append_folkepension_findings(
    findings: list[PlanningRiskFinding],
    result: HouseholdProjectionResult,
) -> None:
    for fp_result in result.folkepension_results:
        if fp_result.result.tillaeg_before_modregning_dkk > Decimal(
            "0"
        ) and fp_result.result.tillaeg_after_modregning_dkk == Decimal("0"):
            findings.append(
                PlanningRiskFinding(
                    code="folkepension_tillaeg_fully_reduced",
                    severity="warning",
                    message=(
                        f"{fp_result.entity} Folkepension pension supplement is fully reduced."
                    ),
                    source_assumption="Folkepension private pension income means-test",
                    next_action=(
                        "Review private pension payout level and Folkepension "
                        "means-test assumptions."
                    ),
                )
            )
        elif fp_result.result.modregning_dkk > Decimal("0"):
            findings.append(
                PlanningRiskFinding(
                    code="folkepension_reduced",
                    severity="warning",
                    message=f"{fp_result.entity} Folkepension pension supplement is reduced.",
                    source_assumption="Folkepension private pension income means-test",
                    next_action=(
                        "Review private pension payout level and Folkepension "
                        "means-test assumptions."
                    ),
                )
            )


def _append_ask_findings(
    findings: list[PlanningRiskFinding],
    result: HouseholdProjectionResult,
    contribution_strategy: ContributionStrategyExplanation | None,
) -> None:
    for projection in result.liquid_projections:
        if projection.config.account_type != "ask":
            continue
        overflow = next(
            (flow for flow in projection.flows if flow.contribution_overflow_dkk > Decimal("0")),
            None,
        )
        if overflow is not None:
            findings.append(
                PlanningRiskFinding(
                    code="ask_cap_reached",
                    severity="warning",
                    affected_year=overflow.year,
                    message="ASK cap is reached and contributions overflow to frie midler.",
                    source_assumption="ASK deposit cap and liquid contribution schedule",
                    next_action=(
                        "Route further monthly savings to frie midler after cap exhaustion."
                    ),
                )
            )
            break
    if contribution_strategy is not None:
        for warning in contribution_strategy.warnings:
            findings.append(
                PlanningRiskFinding(
                    code=warning.code,
                    severity="warning",
                    affected_year=contribution_strategy.ask_cap_exhaustion_year,
                    message=warning.message,
                    source_assumption="ContributionRouter.ask_cumulative_deposits_dkk",
                    next_action="Use the contribution strategy split for future savings.",
                )
            )


def _append_projection_warning_findings(
    findings: list[PlanningRiskFinding],
    result: HouseholdProjectionResult,
) -> None:
    for warning in result.warnings:
        findings.append(
            PlanningRiskFinding(
                code=warning.code,
                severity="warning",
                message=warning.message,
                source_assumption="HouseholdProjectionResult.warnings",
                next_action="Inspect and correct the referenced projection input.",
            )
        )
