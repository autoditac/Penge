"""Render :class:`~penge.ops.report.model.ReportData` to Markdown."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

from .charts import render_bar, render_pie, render_sparkline
from .model import (
    AllocationSection,
    CashflowSection,
    FireSection,
    HeaderSection,
    NetWorthSection,
    OpsSection,
    ReportData,
    TaxSection,
)
from .redact import redact_text

_TWO_DP = Decimal("0.01")


def _fmt(value: Decimal | None, *, suffix: str = "") -> str:
    if value is None:
        return "—"
    q = value.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)
    sep = " " if suffix else ""
    return f"{q:,}{sep}{suffix}"


def _fmt_int(value: int | None) -> str:
    return "—" if value is None else f"{value:,}"


def _safe(value: str) -> str:
    """Redact + minimally escape for Markdown."""
    redacted = redact_text(value)
    return redacted.replace("|", "\\|").replace("\n", " ")


def render_markdown(data: ReportData, out_dir: Path) -> str:
    """Render the report Markdown and write any chart PNGs into ``out_dir``.

    Returns the Markdown body. The caller is responsible for writing
    it to ``out_dir/report.md`` — keeping I/O at the boundary makes
    the renderer trivially unit-testable.
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    parts.append(_render_header(data.header))
    parts.append(_render_net_worth(data.net_worth, out_dir))
    parts.append(_render_cashflow(data.cashflow, out_dir))
    parts.append(_render_allocation(data.allocation, out_dir))
    parts.append(_render_tax(data.tax))
    parts.append(_render_fire(data.fire))
    parts.append(_render_ops(data.ops))
    return "\n\n".join(parts).rstrip() + "\n"


def _todo(note: str) -> str:
    msg = note or "data source not yet wired"
    return f"> **TODO** — {_safe(msg)}"


def _append_note(lines: list[str], note: str) -> None:
    """Append a TODO/note block when a section has a non-empty note even though
    it rendered as available. Without this the note (e.g. "per-category
    breakdown pending") would be silently dropped.
    """

    if note:
        lines.append("")
        lines.append(_todo(note))


def _render_header(header: HeaderSection) -> str:
    versions = ", ".join(f"{k}={v}" for k, v in sorted(header.schema_versions.items())) or "—"
    return (
        f"# Penge monthly report — {header.month}\n\n"
        f"- **Generated at:** {header.generated_at.isoformat()}\n"
        f"- **Git SHA:** `{header.git_sha}`\n"
        f"- **Schema versions:** {versions}\n"
    )


def _render_net_worth(section: NetWorthSection, out_dir: Path) -> str:
    lines = ["## Net worth\n"]
    if not section.available:
        lines.append(_todo(section.note))
        return "\n".join(lines)

    lines.append(f"- **End of month (EUR):** {_fmt(section.eom_eur, suffix='EUR')}")
    lines.append(f"- **End of month (DKK):** {_fmt(section.eom_dkk, suffix='DKK')}")
    lines.append(f"- **MoM Δ (EUR):** {_fmt(section.mom_delta_eur, suffix='EUR')}")
    lines.append(f"- **YoY Δ (EUR):** {_fmt(section.yoy_delta_eur, suffix='EUR')}")

    chart = render_sparkline(out_dir, section.sparkline_eur)
    lines.append("")
    lines.append(f"![Net worth sparkline]({chart})")
    _append_note(lines, section.note)
    return "\n".join(lines)


def _render_cashflow(section: CashflowSection, out_dir: Path) -> str:
    lines = ["## Cashflow\n"]
    if not section.available:
        lines.append(_todo(section.note))
        return "\n".join(lines)

    lines.append(f"- **Inflow:** {_fmt(section.inflow_eur, suffix='EUR')}")
    lines.append(f"- **Outflow:** {_fmt(section.outflow_eur, suffix='EUR')}")
    lines.append(f"- **Net:** {_fmt(section.net_eur, suffix='EUR')}")
    lines.append("")
    lines.append("### Top categories\n")
    lines.append("| Category | Amount (EUR) |")
    lines.append("| --- | ---: |")
    if section.top_categories:
        for label, amount in section.top_categories[:5]:
            lines.append(f"| {_safe(label)} | {_fmt(amount)} |")
    else:
        lines.append("| _none_ | — |")
    chart = render_bar(
        out_dir,
        [(label, amount) for label, amount in section.top_categories[:5]],
        title="Top cashflow categories (EUR)",
        filename="cashflow_categories.png",
    )
    lines.append("")
    lines.append(f"![Top cashflow categories]({chart})")
    _append_note(lines, section.note)
    return "\n".join(lines)


def _render_allocation(section: AllocationSection, out_dir: Path) -> str:
    lines = ["## Asset allocation\n"]
    if not section.available:
        lines.append(_todo(section.note))
        return "\n".join(lines)

    lines.append("### By asset class\n")
    lines.append("| Class | EUR | Share |")
    lines.append("| --- | ---: | ---: |")
    for label, value, share in section.by_class:
        lines.append(f"| {_safe(label)} | {_fmt(value)} | {_fmt(share * Decimal(100))} % |")
    chart_a = render_pie(
        out_dir,
        section.by_class,
        title="Allocation by class",
        filename="allocation_by_class.png",
    )
    lines.append("")
    lines.append(f"![Allocation by class]({chart_a})")

    lines.append("")
    lines.append("### By jurisdiction\n")
    lines.append("| Jurisdiction | EUR | Share |")
    lines.append("| --- | ---: | ---: |")
    for label, value, share in section.by_jurisdiction:
        lines.append(f"| {_safe(label)} | {_fmt(value)} | {_fmt(share * Decimal(100))} % |")
    chart_b = render_pie(
        out_dir,
        section.by_jurisdiction,
        title="Allocation by jurisdiction",
        filename="allocation_by_jurisdiction.png",
    )
    lines.append("")
    lines.append(f"![Allocation by jurisdiction]({chart_b})")
    _append_note(lines, section.note)
    return "\n".join(lines)


def _render_tax(section: TaxSection) -> str:
    lines = ["## Tax preview (YTD)\n"]
    if not section.available:
        lines.append(_todo(section.note))
        return "\n".join(lines)

    lines.append(f"- **DK estimate:** {_fmt(section.dk_estimate_dkk, suffix='DKK')}")
    if section.dk_components:
        lines.append("")
        lines.append("| DK component | DKK |")
        lines.append("| --- | ---: |")
        for label, amount in section.dk_components:
            lines.append(f"| {_safe(label)} | {_fmt(amount)} |")
    lines.append("")
    lines.append(f"- **DE estimate:** {_fmt(section.de_estimate_eur, suffix='EUR')}")
    if section.de_components:
        lines.append("")
        lines.append("| DE component | EUR |")
        lines.append("| --- | ---: |")
        for label, amount in section.de_components:
            lines.append(f"| {_safe(label)} | {_fmt(amount)} |")
    _append_note(lines, section.note)
    return "\n".join(lines)


def _render_fire(section: FireSection) -> str:
    lines = ["## FIRE projection snapshot\n"]
    if not section.available:
        lines.append(_todo(section.note))
        return "\n".join(lines)

    lines.append(f"- **Horizon year:** {_fmt_int(section.horizon_year)}")
    lines.append(f"- **P10 portfolio:** {_fmt(section.p10_eur, suffix='EUR')}")
    lines.append(f"- **P50 portfolio:** {_fmt(section.p50_eur, suffix='EUR')}")
    lines.append(f"- **P90 portfolio:** {_fmt(section.p90_eur, suffix='EUR')}")
    p_goal = section.p_goal_met
    p_goal_pct = None if p_goal is None else (p_goal * Decimal(100))
    lines.append(f"- **P(goal met):** {_fmt(p_goal_pct, suffix='%')}")
    lines.append(f"- **Median FIRE year:** {_fmt_int(section.median_fire_year)}")
    _append_note(lines, section.note)
    return "\n".join(lines)


def _render_ops(section: OpsSection) -> str:
    lines = ["## Operations\n"]
    if not section.available:
        lines.append(_todo(section.note))
        return "\n".join(lines)

    lines.append(f"- **Vault — classified last month:** {_fmt_int(section.vault_classified)}")
    lines.append(f"- **Vault — unsorted last month:** {_fmt_int(section.vault_unsorted)}")
    backup_age = (
        "—" if section.last_backup_age_days is None else f"{section.last_backup_age_days} days ago"
    )
    backup_at = "—" if section.last_backup_at is None else section.last_backup_at.isoformat()
    lines.append(f"- **Last backup:** {backup_at} ({backup_age})")
    lines.append(f"- **Sentry errors (last 30d):** {_fmt_int(section.sentry_errors_last_month)}")
    _append_note(lines, section.note)
    return "\n".join(lines)
