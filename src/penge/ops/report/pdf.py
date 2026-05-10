"""Render :class:`~penge.ops.report.model.ReportData` to PDF via reportlab.

We use reportlab (already pinned in the ``parsers`` group) rather than
WeasyPrint to avoid the native cairo / pango / gdk-pixbuf stack on
operator machines and CI runners. The output is a flowing Story of
paragraphs / tables / inline charts — visually simpler than the HTML
Markdown render but information-equivalent.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

from .charts import render_bar, render_pie, render_sparkline
from .model import (
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
    return redact_text(value)


def render_pdf(data: ReportData, out_dir: Path, *, filename: str = "report.pdf") -> Path:
    """Render the PDF and return its absolute path.

    Charts are re-rendered into ``out_dir`` so the PDF can be moved /
    served standalone without losing its embedded images.
    """

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        TableStyle,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / filename

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm,
        title=f"Penge monthly report {data.header.month}",
        author="Penge",
    )
    styles = getSampleStyleSheet()
    ctx = _PdfCtx(
        out_dir=out_dir,
        colors=colors,
        cm=cm,
        table_style_cls=TableStyle,
        h1=styles["Heading1"],
        h2=styles["Heading2"],
        body=styles["BodyText"],
    )

    story: list[Any] = []
    story.append(Paragraph(f"Penge monthly report — {data.header.month}", ctx.h1))
    story.append(Paragraph(_header_html(data.header), ctx.body))
    story.append(Spacer(1, 0.4 * cm))

    _append_net_worth(story, data, ctx)
    story.append(Spacer(1, 0.4 * cm))
    _append_cashflow(story, data, ctx)
    story.append(PageBreak())
    _append_allocation(story, data, ctx)
    story.append(PageBreak())
    _append_kv_section(story, "Tax preview (YTD)", data.tax, _tax_rows, ctx)
    story.append(Spacer(1, 0.4 * cm))
    _append_kv_section(story, "FIRE projection snapshot", data.fire, _fire_rows, ctx)
    story.append(Spacer(1, 0.4 * cm))
    _append_kv_section(story, "Operations", data.ops, _ops_rows, ctx)

    doc.build(story)
    return pdf_path


@dataclass(frozen=True)
class _PdfCtx:
    out_dir: Path
    colors: Any
    cm: Any
    table_style_cls: Any
    h1: Any
    h2: Any
    body: Any


def _append_net_worth(story: list[Any], data: ReportData, ctx: _PdfCtx) -> None:
    from reportlab.platypus import Image, Paragraph, Spacer

    story.append(Paragraph("Net worth", ctx.h2))
    section = data.net_worth
    if not section.available:
        story.append(_todo_para(section.note, ctx.body))
        return
    story.append(_kv_table(_net_worth_rows(section), ctx.table_style_cls, ctx.colors))
    chart = render_sparkline(ctx.out_dir, section.sparkline_eur)
    story.append(Spacer(1, 0.3 * ctx.cm))
    story.append(Image(str(ctx.out_dir / chart), width=16 * ctx.cm, height=4.5 * ctx.cm))
    _append_note_para(story, section.note, ctx.body)


def _append_cashflow(story: list[Any], data: ReportData, ctx: _PdfCtx) -> None:
    from reportlab.platypus import Image, Paragraph, Spacer

    story.append(Paragraph("Cashflow", ctx.h2))
    section = data.cashflow
    if not section.available:
        story.append(_todo_para(section.note, ctx.body))
        return
    story.append(_kv_table(_cashflow_rows(section), ctx.table_style_cls, ctx.colors))
    if section.top_categories:
        story.append(Spacer(1, 0.2 * ctx.cm))
        story.append(
            _two_col_table(
                "Category",
                "EUR",
                [(_safe(lbl), _fmt(amt)) for lbl, amt in section.top_categories[:5]],
                ctx.table_style_cls,
                ctx.colors,
            )
        )
    chart = render_bar(
        ctx.out_dir,
        list(section.top_categories[:5]),
        title="Top cashflow categories (EUR)",
        filename="cashflow_categories.png",
    )
    story.append(Spacer(1, 0.3 * ctx.cm))
    story.append(Image(str(ctx.out_dir / chart), width=16 * ctx.cm, height=6.5 * ctx.cm))
    _append_note_para(story, section.note, ctx.body)


def _append_allocation(story: list[Any], data: ReportData, ctx: _PdfCtx) -> None:
    from reportlab.platypus import Image, Paragraph, Spacer

    story.append(Paragraph("Asset allocation", ctx.h2))
    section = data.allocation
    if not section.available:
        story.append(_todo_para(section.note, ctx.body))
        return
    story.append(Paragraph("By asset class", ctx.body))
    story.append(_alloc_table(section.by_class, ctx.table_style_cls, ctx.colors))
    chart_a = render_pie(
        ctx.out_dir,
        section.by_class,
        title="Allocation by class",
        filename="allocation_by_class.png",
    )
    story.append(Spacer(1, 0.2 * ctx.cm))
    story.append(Image(str(ctx.out_dir / chart_a), width=10 * ctx.cm, height=10 * ctx.cm))
    story.append(Spacer(1, 0.3 * ctx.cm))
    story.append(Paragraph("By jurisdiction", ctx.body))
    story.append(_alloc_table(section.by_jurisdiction, ctx.table_style_cls, ctx.colors))
    chart_b = render_pie(
        ctx.out_dir,
        section.by_jurisdiction,
        title="Allocation by jurisdiction",
        filename="allocation_by_jurisdiction.png",
    )
    story.append(Spacer(1, 0.2 * ctx.cm))
    story.append(Image(str(ctx.out_dir / chart_b), width=10 * ctx.cm, height=10 * ctx.cm))
    _append_note_para(story, section.note, ctx.body)


def _append_kv_section(
    story: list[Any],
    title: str,
    section: Any,
    rows_fn: Any,
    ctx: _PdfCtx,
) -> None:
    from reportlab.platypus import Paragraph

    story.append(Paragraph(title, ctx.h2))
    if not section.available:
        story.append(_todo_para(section.note, ctx.body))
        return
    story.append(_kv_table(rows_fn(section), ctx.table_style_cls, ctx.colors))
    _append_note_para(story, section.note, ctx.body)


# ---------------------------------------------------------------------------
# Helpers — none of these import reportlab at module load time.
# ---------------------------------------------------------------------------


def _header_html(header: HeaderSection) -> str:
    versions = ", ".join(f"{k}={v}" for k, v in sorted(header.schema_versions.items())) or "—"
    return (
        f"<b>Generated at:</b> {header.generated_at.isoformat()}<br/>"
        f"<b>Git SHA:</b> <font face='Courier'>{header.git_sha}</font><br/>"
        f"<b>Schema versions:</b> {versions}"
    )


def _append_note_para(story: list[Any], note: str, body_style: Any) -> None:
    """Append a TODO/note paragraph when an available section has a non-empty
    note. Mirrors markdown._append_note so partial data sources are surfaced
    rather than silently dropped.
    """

    if note:
        story.append(_todo_para(note, body_style))


def _todo_para(note: str, body_style: Any) -> Any:
    from reportlab.platypus import Paragraph

    msg = note or "data source not yet wired"
    return Paragraph(f"<b>TODO</b> — {_safe(msg)}", body_style)


def _kv_table(
    rows: list[tuple[str, str]],
    table_style_cls: Any,
    colors_mod: Any,
) -> Any:
    from reportlab.platypus import Table

    table = Table(rows, colWidths=[6 * 28, 6 * 28], hAlign="LEFT")
    table.setStyle(
        table_style_cls(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
                ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors_mod.lightgrey),
            ]
        )
    )
    return table


def _two_col_table(
    header_a: str,
    header_b: str,
    rows: list[tuple[str, str]],
    table_style_cls: Any,
    colors_mod: Any,
) -> Any:
    from reportlab.platypus import Table

    data: list[tuple[str, str]] = [(header_a, header_b), *rows]
    table = Table(data, colWidths=[10 * 28, 6 * 28], hAlign="LEFT")
    table.setStyle(
        table_style_cls(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors_mod.whitesmoke),
                ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors_mod.lightgrey),
            ]
        )
    )
    return table


def _alloc_table(
    entries: list[tuple[str, Decimal, Decimal]],
    table_style_cls: Any,
    colors_mod: Any,
) -> Any:
    rows: list[tuple[str, str]] = []
    for label, value, share in entries:
        pct = (share * Decimal(100)).quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)
        rows.append((_safe(label), f"{_fmt(value)} EUR ({pct} %)"))
    if not rows:
        rows = [("(none)", "—")]
    return _kv_table(rows, table_style_cls, colors_mod)


def _net_worth_rows(section: NetWorthSection) -> list[tuple[str, str]]:
    return [
        ("End of month (EUR)", _fmt(section.eom_eur, suffix="EUR")),
        ("End of month (DKK)", _fmt(section.eom_dkk, suffix="DKK")),
        ("MoM Δ (EUR)", _fmt(section.mom_delta_eur, suffix="EUR")),
        ("YoY Δ (EUR)", _fmt(section.yoy_delta_eur, suffix="EUR")),
    ]


def _cashflow_rows(section: CashflowSection) -> list[tuple[str, str]]:
    return [
        ("Inflow", _fmt(section.inflow_eur, suffix="EUR")),
        ("Outflow", _fmt(section.outflow_eur, suffix="EUR")),
        ("Net", _fmt(section.net_eur, suffix="EUR")),
    ]


def _tax_rows(section: TaxSection) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = [
        ("DK estimate", _fmt(section.dk_estimate_dkk, suffix="DKK")),
    ]
    for label, amount in section.dk_components:
        rows.append((f"  • {_safe(label)} (DKK)", _fmt(amount)))
    rows.append(("DE estimate", _fmt(section.de_estimate_eur, suffix="EUR")))
    for label, amount in section.de_components:
        rows.append((f"  • {_safe(label)} (EUR)", _fmt(amount)))
    return rows


def _fire_rows(section: FireSection) -> list[tuple[str, str]]:
    p_goal_pct: Decimal | None = (
        None if section.p_goal_met is None else section.p_goal_met * Decimal(100)
    )
    return [
        ("Horizon year", _fmt_int(section.horizon_year)),
        ("P10 portfolio", _fmt(section.p10_eur, suffix="EUR")),
        ("P50 portfolio", _fmt(section.p50_eur, suffix="EUR")),
        ("P90 portfolio", _fmt(section.p90_eur, suffix="EUR")),
        ("P(goal met)", _fmt(p_goal_pct, suffix="%")),
        ("Median FIRE year", _fmt_int(section.median_fire_year)),
    ]


def _ops_rows(section: OpsSection) -> list[tuple[str, str]]:
    backup_at = "—" if section.last_backup_at is None else section.last_backup_at.isoformat()
    backup_age = (
        "—" if section.last_backup_age_days is None else f"{section.last_backup_age_days} days ago"
    )
    return [
        ("Vault — classified last month", _fmt_int(section.vault_classified)),
        ("Vault — unsorted last month", _fmt_int(section.vault_unsorted)),
        ("Last backup", f"{backup_at} ({backup_age})"),
        ("Sentry errors (last 30d)", _fmt_int(section.sentry_errors_last_month)),
    ]
