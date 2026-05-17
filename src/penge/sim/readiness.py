"""Retirement readiness reporting for household projections."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal

import pydantic

from penge.sim.balance import HouseholdBalanceSheet, project_balance_sheet
from penge.sim.bridge_spending import (
    BridgeSafeSpendingResult,
    summarize_bridge_result,
)
from penge.sim.contribution_strategy import ContributionStrategyExplanation
from penge.sim.plan import HouseholdProjectionResult
from penge.sim.risk import PlanningRiskRegister, generate_risk_register
from penge.sim.tax_timeline import TaxTimeline, build_tax_timeline

__all__ = [
    "ReadinessFinding",
    "RetirementReadinessReport",
    "generate_readiness_report",
]

_TWO_DP = Decimal("0.01")


def _fmt(value: Decimal, suffix: str) -> str:
    return f"{value.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN):,} {suffix}"


class ReadinessFinding(pydantic.BaseModel):
    """Named readiness finding suitable for reports and UI surfaces."""

    model_config = pydantic.ConfigDict(frozen=True)

    code: str
    severity: Literal["info", "warning", "critical"]
    message: str
    year: int | None = None
    next_action: str | None = None


class RetirementReadinessReport(pydantic.BaseModel):
    """Structured retirement readiness report."""

    model_config = pydantic.ConfigDict(frozen=True)

    conclusion: Literal["ready", "watch", "not_ready"]
    planned_retirement_year: int
    balance_sheet: HouseholdBalanceSheet
    bridge_assessments: tuple[BridgeSafeSpendingResult, ...]
    tax_timeline: TaxTimeline
    risk_register: PlanningRiskRegister
    contribution_strategy: ContributionStrategyExplanation | None = None
    findings: tuple[ReadinessFinding, ...]
    total_liquid_tax_dkk: Decimal
    total_bridge_tax_dkk: Decimal
    markdown: str


def generate_readiness_report(
    result: HouseholdProjectionResult,
    *,
    contribution_strategy: ContributionStrategyExplanation | None = None,
) -> RetirementReadinessReport:
    """Generate a structured Markdown readiness report from a household projection."""

    balance_sheet = project_balance_sheet(result)
    bridge_assessments = _bridge_assessments(result)
    tax_timeline = build_tax_timeline(result)
    risk_register = generate_risk_register(
        result,
        tax_timeline=tax_timeline,
        balance_sheet=balance_sheet,
        contribution_strategy=contribution_strategy,
    )
    findings = _findings(risk_register)
    conclusion: Literal["ready", "watch", "not_ready"] = "ready"
    if any(finding.severity == "critical" for finding in findings):
        conclusion = "not_ready"
    elif any(finding.severity == "warning" for finding in findings):
        conclusion = "watch"

    total_liquid_tax = sum(
        (projection.total_tax_due_dkk() for projection in result.liquid_projections),
        Decimal("0"),
    )
    total_bridge_tax = sum(
        (bridge.result.total_tax_paid_dkk for bridge in result.bridge_results),
        Decimal("0"),
    )
    report = RetirementReadinessReport(
        conclusion=conclusion,
        planned_retirement_year=max(member.retirement_year for member in result.plan.members),
        balance_sheet=balance_sheet,
        bridge_assessments=bridge_assessments,
        tax_timeline=tax_timeline,
        risk_register=risk_register,
        contribution_strategy=contribution_strategy,
        findings=findings,
        total_liquid_tax_dkk=total_liquid_tax,
        total_bridge_tax_dkk=total_bridge_tax,
        markdown="",
    )
    return report.model_copy(update={"markdown": _render_markdown(report, result)})


def _bridge_assessments(
    result: HouseholdProjectionResult,
) -> tuple[BridgeSafeSpendingResult, ...]:
    assessments: list[BridgeSafeSpendingResult] = []
    templates = {template.entity: template for template in result.plan.bridge_templates}
    for entity_result in result.bridge_results:
        template = templates[entity_result.entity]
        flow = entity_result.result.monthly_flows[0]
        assessments.append(
            summarize_bridge_result(
                entity_result.result,
                starting_balance_dkk=flow.opening_balance_dkk,
                cost_basis_dkk=flow.cost_basis_dkk,
                start_year=template.bridge_start_year + 1,
            )
        )
    return tuple(assessments)


def _findings(risk_register: PlanningRiskRegister) -> tuple[ReadinessFinding, ...]:
    return tuple(
        ReadinessFinding(
            code=finding.code,
            severity=finding.severity,
            message=finding.message,
            year=finding.affected_year,
            next_action=finding.next_action,
        )
        for finding in risk_register.findings
    )


def _render_markdown(
    report: RetirementReadinessReport,
    result: HouseholdProjectionResult,
) -> str:
    lines = [
        "# Retirement readiness report",
        "",
        f"**Conclusion:** {report.conclusion}",
        f"**Planned retirement year:** {report.planned_retirement_year}",
        "",
        "## Findings",
        "",
        "| Severity | Code | Year | Finding | Next action |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for finding in report.findings:
        year = "n/a" if finding.year is None else str(finding.year)
        next_action = finding.next_action or "n/a"
        lines.append(
            f"| {finding.severity} | `{finding.code}` | {year} | "
            f"{finding.message} | {next_action} |"
        )

    lines.extend(
        [
            "",
            "## Bridge summary",
            "",
            "| Horizon | Max net monthly spending | Depletion | Tax paid |",
            "| ---: | ---: | ---: | ---: |",
        ]
    )
    if report.bridge_assessments:
        for assessment in report.bridge_assessments:
            depletion = (
                str(assessment.depletion_year)
                if assessment.depletion_year is not None
                else f"month {assessment.depletion_month}"
            )
            lines.append(
                f"| {assessment.horizon_months} months | "
                f"{_fmt(assessment.max_monthly_net_spending_dkk, 'DKK')} | "
                f"{depletion} | {_fmt(assessment.total_tax_paid_dkk, 'DKK')} |"
            )
    else:
        lines.append("| n/a | n/a | n/a | n/a |")

    lines.extend(
        [
            "",
            "## Balance sheet and liquidity runway",
            "",
            "| Year | Spendable liquidity | Locked pension | Total net worth | Runway |",
            "| ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report.balance_sheet.rows[:5]:
        runway = (
            "n/a"
            if row.liquidity_runway_months is None
            else f"{row.liquidity_runway_months} months"
        )
        lines.append(
            f"| {row.year} | {_fmt(row.spendable_liquidity_dkk, 'DKK')} | "
            f"{_fmt(row.locked_pension_dkk, 'DKK')} | "
            f"{_fmt(row.total_net_worth_dkk, 'DKK')} | {runway} |"
        )

    lines.extend(
        [
            "",
            "## Tax drag summary",
            "",
            f"- **Liquid depot tax:** {_fmt(report.total_liquid_tax_dkk, 'DKK')}",
            f"- **Bridge tax:** {_fmt(report.total_bridge_tax_dkk, 'DKK')}",
            f"- **Total timeline tax drag:** "
            f"{_fmt(report.tax_timeline.totals.total_tax_drag_dkk, 'DKK')}",
            "",
            "| Year | ASK tax | Frie midler tax | Topskat | Folkepension reduction | Total |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for tax_row in report.tax_timeline.rows[:5]:
        lines.append(
            f"| {tax_row.year} | {_fmt(tax_row.ask_tax_dkk, 'DKK')} | "
            f"{_fmt(tax_row.frie_midler_aktieindkomst_tax_dkk, 'DKK')} | "
            f"{_fmt(tax_row.estimated_topskat_dkk, 'DKK')} | "
            f"{_fmt(tax_row.folkepension_modregning_dkk, 'DKK')} | "
            f"{_fmt(tax_row.total_tax_drag_dkk, 'DKK')} |"
        )

    lines.extend(
        [
            "",
            "## Pension payout and Folkepension",
            "",
        ]
    )
    if result.payout_projections:
        for payout in result.payout_projections:
            lines.append(
                f"- **{payout.config.entity}:** "
                f"{_fmt(payout.total_monthly_gross_eur, 'EUR/month')} gross pension payout."
            )
    else:
        lines.append("- No pension payout projections were produced.")
    for fp_result in result.folkepension_results:
        lines.append(
            f"- **{fp_result.entity}:** "
            f"{_fmt(fp_result.result.total_monthly_dkk, 'DKK/month')} Folkepension."
        )

    if report.contribution_strategy is not None:
        strategy = report.contribution_strategy
        exhaustion = (
            "not in horizon"
            if strategy.ask_cap_exhaustion_month is None
            else f"month {strategy.ask_cap_exhaustion_month} ({strategy.ask_cap_exhaustion_year})"
        )
        lines.extend(
            [
                "",
                "## Contribution strategy",
                "",
                strategy.summary,
                "",
                "| Total to ASK | Total to frie midler | "
                "ASK cap exhaustion | Onward monthly split |",
                "| ---: | ---: | --- | --- |",
                f"| {_fmt(strategy.total_to_ask_dkk, 'DKK')} | "
                f"{_fmt(strategy.total_to_frie_midler_dkk, 'DKK')} | "
                f"{exhaustion} | "
                f"{_fmt(strategy.onward_monthly_ask_dkk, 'DKK')} ASK / "
                f"{_fmt(strategy.onward_monthly_frie_midler_dkk, 'DKK')} frie |",
            ]
        )

    lines.extend(
        [
            "",
            "## Assumptions",
            "",
            "| Key | Value | Source |",
            "| --- | --- | --- |",
        ]
    )
    for assumption in result.audit_record.assumptions[:10]:
        lines.append(
            f"| `{assumption.name}` | {assumption.value} {assumption.unit} | "
            f"{assumption.source} |"
        )
    return "\n".join(lines) + "\n"
