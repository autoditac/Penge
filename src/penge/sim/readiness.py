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
from penge.sim.plan import HouseholdProjectionResult

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
    findings: tuple[ReadinessFinding, ...]
    total_liquid_tax_dkk: Decimal
    total_bridge_tax_dkk: Decimal
    markdown: str


def generate_readiness_report(
    result: HouseholdProjectionResult,
) -> RetirementReadinessReport:
    """Generate a structured Markdown readiness report from a household projection."""

    balance_sheet = project_balance_sheet(result)
    bridge_assessments = _bridge_assessments(result)
    findings = _findings(result, balance_sheet, bridge_assessments)
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


def _findings(
    result: HouseholdProjectionResult,
    balance_sheet: HouseholdBalanceSheet,
    bridge_assessments: tuple[BridgeSafeSpendingResult, ...],
) -> tuple[ReadinessFinding, ...]:
    findings: list[ReadinessFinding] = []
    depletion = balance_sheet.first_liquidity_depletion()
    if depletion is not None:
        findings.append(
            ReadinessFinding(
                code="liquidity_depleted",
                severity="critical",
                year=depletion.year,
                message=(
                    "Spendable liquidity is depleted while planned spending remains positive."
                ),
                next_action="Lower bridge spending, retire later, or increase liquid capital.",
            )
        )
    for warning in result.warnings:
        findings.append(
            ReadinessFinding(
                code=warning.code,
                severity="warning",
                message=warning.message,
                next_action="Inspect the projection warning and fix the underlying input.",
            )
        )
    for assessment in bridge_assessments:
        if assessment.final_balance_dkk < Decimal("-1"):
            findings.append(
                ReadinessFinding(
                    code="bridge_depletes_early",
                    severity="critical",
                    year=assessment.depletion_year,
                    message="Bridge depot depletes before the requested pension horizon.",
                    next_action="Reduce bridge spending or increase starting bridge capital.",
                )
            )
    for fp_result in result.folkepension_results:
        if fp_result.result.modregning_dkk > Decimal("0"):
            findings.append(
                ReadinessFinding(
                    code="folkepension_reduced",
                    severity="warning",
                    message=(
                        f"{fp_result.entity} Folkepension pension supplement is reduced by "
                        f"{_fmt(fp_result.result.modregning_dkk, 'DKK/month')}."
                    ),
                    next_action="Review private pension payout level and means-test assumptions.",
                )
            )
    if not findings:
        findings.append(
            ReadinessFinding(
                code="no_material_findings",
                severity="info",
                message="No material readiness warnings were detected in this projection.",
            )
        )
    return tuple(findings)


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
