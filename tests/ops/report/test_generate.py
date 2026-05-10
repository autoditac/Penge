"""End-to-end tests for the monthly report generator.

The fixtures are synthetic by construction — no real account numbers,
no real names. The redaction pass is also exercised explicitly via
``test_redact_strips_synthetic_pii``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from penge.ops.report import generate_report
from penge.ops.report.generate import main as cli_main
from penge.ops.report.model import (
    AllocationSection,
    CashflowSection,
    FireSection,
    HeaderSection,
    NetWorthSection,
    OpsSection,
    ReportData,
    TaxSection,
)
from penge.ops.report.redact import redact_mapping, redact_text


def _synthetic_payload() -> ReportData:
    """Hand-crafted, redaction-safe fixture for the full happy path."""

    header = HeaderSection(
        month="2026-04",
        generated_at=datetime(2026, 5, 1, 7, 30, tzinfo=UTC),
        schema_versions={"alembic": "abc1234"},
        git_sha="deadbee",
    )
    net_worth = NetWorthSection(
        available=True,
        eom_eur=Decimal("250000.00"),
        eom_dkk=Decimal("1862500.00"),
        mom_delta_eur=Decimal("1500.00"),
        yoy_delta_eur=Decimal("18000.00"),
        sparkline_eur=[(f"2025-{m:02d}", Decimal(str(200000 + m * 4000))) for m in range(5, 13)]
        + [(f"2026-{m:02d}", Decimal(str(232000 + m * 4500))) for m in range(1, 5)],
    )
    cashflow = CashflowSection(
        available=True,
        inflow_eur=Decimal("6800.00"),
        outflow_eur=Decimal("4200.00"),
        net_eur=Decimal("2600.00"),
        top_categories=[
            ("Groceries", Decimal("-650.00")),
            ("Rent", Decimal("-1400.00")),
            ("Salary household-A", Decimal("4200.00")),
            ("Transport", Decimal("-310.00")),
            ("Utilities", Decimal("-220.00")),
        ],
    )
    allocation = AllocationSection(
        available=True,
        by_class=[
            ("Equity", Decimal("150000"), Decimal("0.60")),
            ("Bond", Decimal("50000"), Decimal("0.20")),
            ("Cash", Decimal("30000"), Decimal("0.12")),
            ("Real estate", Decimal("20000"), Decimal("0.08")),
        ],
        by_jurisdiction=[
            ("DK", Decimal("120000"), Decimal("0.48")),
            ("DE", Decimal("90000"), Decimal("0.36")),
            ("Global", Decimal("40000"), Decimal("0.16")),
        ],
    )
    tax = TaxSection(
        available=True,
        dk_estimate_dkk=Decimal("12000.00"),
        dk_components=[("Lagerbeskatning", Decimal("8000")), ("PAL", Decimal("4000"))],
        de_estimate_eur=Decimal("950.00"),
        de_components=[("Vorabpauschale", Decimal("950"))],
    )
    fire = FireSection(
        available=True,
        horizon_year=2055,
        p10_eur=Decimal("450000"),
        p50_eur=Decimal("1200000"),
        p90_eur=Decimal("2600000"),
        p_goal_met=Decimal("0.72"),
        median_fire_year=2047,
    )
    ops = OpsSection(
        available=True,
        vault_classified=42,
        vault_unsorted=3,
        last_backup_at=date(2026, 4, 30),
        last_backup_age_days=1,
        sentry_errors_last_month=0,
    )
    return ReportData(
        header=header,
        net_worth=net_worth,
        cashflow=cashflow,
        allocation=allocation,
        tax=tax,
        fire=fire,
        ops=ops,
    )


def test_generate_report_writes_md_and_pdf(tmp_path: Path) -> None:
    md_path, pdf_path = generate_report("2026-04", tmp_path, data=_synthetic_payload())

    assert md_path.is_file()
    assert pdf_path.is_file()
    assert md_path == tmp_path / "2026-04" / "report.md"
    assert pdf_path == tmp_path / "2026-04" / "report.pdf"

    md_text = md_path.read_text(encoding="utf-8")
    for heading in (
        "# Penge monthly report — 2026-04",
        "## Net worth",
        "## Cashflow",
        "## Asset allocation",
        "## Tax preview (YTD)",
        "## FIRE projection snapshot",
        "## Operations",
    ):
        assert heading in md_text, f"missing heading: {heading}"

    # Charts must exist as PNG sidecars and be referenced from the MD.
    charts = {
        "net_worth_sparkline.png",
        "cashflow_categories.png",
        "allocation_by_class.png",
        "allocation_by_jurisdiction.png",
    }
    for chart in charts:
        chart_path = tmp_path / "2026-04" / chart
        assert chart_path.is_file(), f"missing chart: {chart}"
        assert chart_path.stat().st_size > 0
        assert chart in md_text

    # PDF must be a non-empty file with the PDF magic bytes.
    assert pdf_path.stat().st_size > 0
    assert pdf_path.read_bytes()[:5] == b"%PDF-"


def test_placeholder_payload_renders_todo_notes(tmp_path: Path) -> None:
    """A fully-degraded payload should still render — with TODO markers."""

    header = HeaderSection(
        month="2026-04",
        generated_at=datetime(2026, 5, 1, 7, 30, tzinfo=UTC),
        schema_versions={},
        git_sha="unknown",
    )
    payload = ReportData(
        header=header,
        net_worth=NetWorthSection(available=False, note="no DB"),
        cashflow=CashflowSection(available=False, note="no DB"),
        allocation=AllocationSection(available=False, note="no mart"),
        tax=TaxSection(available=False, note="no calculator"),
        fire=FireSection(available=False, note="no MC config"),
        ops=OpsSection(available=False, note="no aggregations"),
    )
    md_path, pdf_path = generate_report("2026-04", tmp_path, data=payload)
    md_text = md_path.read_text(encoding="utf-8")
    assert md_text.count("**TODO**") == 6
    assert pdf_path.stat().st_size > 0


def test_invalid_month_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="YYYY-MM"):
        generate_report("2026/04", tmp_path)


def test_cli_writes_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI entry point hands off to ``generate_report`` and exits 0."""

    payload = _synthetic_payload()

    def fake_load(month: str) -> ReportData:
        assert month == "2026-04"
        return payload

    monkeypatch.setattr("penge.ops.report.generate.load_report_data", fake_load)

    rc = cli_main(["--month", "2026-04", "--out", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "2026-04" / "report.md").is_file()
    assert (tmp_path / "2026-04" / "report.pdf").is_file()


def test_cli_rejects_bad_month(tmp_path: Path) -> None:
    rc = cli_main(["--month", "26-4", "--out", str(tmp_path)])
    assert rc == 2


def test_redact_strips_synthetic_pii() -> None:
    text = (
        "Owner Erika Mustermann email erika@example.invalid "
        "IBAN DE89370400440532013000 CPR 010101-1234"
    )
    cleaned = redact_text(text)
    assert "erika@example.invalid" not in cleaned
    assert "DE89370400440532013000" not in cleaned
    assert "010101-1234" not in cleaned

    row = {
        "account_id": "abc",
        "iban": "DE89370400440532013000",
        "name": "Erika",
        "email": "erika@example.invalid",
        "balance_eur": 1234,
        "nested": {"tax_id": "X", "ok": "fine"},
    }
    redacted = redact_mapping(row)
    assert redacted["iban"] == "[REDACTED]"
    assert redacted["name"] == "[REDACTED]"
    assert redacted["email"] == "[REDACTED]"
    assert redacted["account_id"] == "[REDACTED]"
    assert redacted["balance_eur"] == 1234
    assert redacted["nested"]["tax_id"] == "[REDACTED]"
    assert redacted["nested"]["ok"] == "fine"


def test_synthetic_label_with_pii_is_redacted_in_md(tmp_path: Path) -> None:
    """Category labels are scrubbed before reaching the rendered MD."""

    payload = _synthetic_payload()
    cashflow_with_pii = CashflowSection(
        available=True,
        inflow_eur=Decimal("100"),
        outflow_eur=Decimal("50"),
        net_eur=Decimal("50"),
        top_categories=[
            ("Transfer to DE89370400440532013000", Decimal("-100.00")),
        ],
    )
    # Build a fresh ReportData since the dataclass is frozen.
    payload = ReportData(
        header=payload.header,
        net_worth=payload.net_worth,
        cashflow=cashflow_with_pii,
        allocation=payload.allocation,
        tax=payload.tax,
        fire=payload.fire,
        ops=payload.ops,
    )
    md_path, _ = generate_report("2026-04", tmp_path, data=payload)
    md_text = md_path.read_text(encoding="utf-8")
    assert "DE89370400440532013000" not in md_text
    assert "[REDACTED]" in md_text
