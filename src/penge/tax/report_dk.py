"""SKAT-format report generator for Danish capital-income tax (#39).

Aggregates the per-instrument / per-account results from the
:mod:`penge.tax.lager`, :mod:`penge.tax.aktiesparekonto`,
:mod:`penge.tax.pal` and :mod:`penge.tax.lots` calculators into a
single, traceable report shaped for the annual SKAT filing.

The report is deliberately *line-oriented* so every number on the
filing can be traced back to a source object via its ``source_id``:

- ``lager:<account>:<isin>``     — one row per :class:`LagerResult`
- ``ask:<account>``              — one row per :class:`AskTaxResult`
- ``pal:<account>``              — one row per :class:`PalResult`
- ``realised:<acc>:<isin>:<n>``  — one row per :class:`RealisedGain`

Outputs:

- :func:`to_csv` — line-numbered CSV ready to hand to the
  Steuerberater / SKAT online form.
- :func:`to_markdown` — human-readable summary that explains each line
  and gives a year total.

Cross-year loss carry-forward is intentionally minimal: the caller
passes a ``prior_loss_carry_forward`` (in DKK) and the report nets it
against the current year's positive capital income. Anything left over
is surfaced as ``loss_carry_forward`` for the next year. The report
does *not* persist the rolling state — that is the consumer's
responsibility (typically the household ledger).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from penge.tax.aktiesparekonto import AskTaxResult
from penge.tax.lager import LagerResult
from penge.tax.lots import Money, RealisedGain
from penge.tax.pal import PAL_RATE, PalResult

__all__ = [
    "SkatReport",
    "SkatReportError",
    "SkatReportRow",
    "build_skat_report",
    "to_csv",
    "to_markdown",
]

_MONEY_DP: Final = Decimal("0.01")
_DKK: Final[Literal["DKK"]] = "DKK"

Category = Literal["lager", "ask", "pal", "realised"]


def _q(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_DP, rounding=ROUND_HALF_EVEN)


def _dkk(amount: Decimal) -> Money:
    return Money(amount=_q(amount), currency=_DKK)


class SkatReportError(Exception):
    """Raised when the inputs to the report are inconsistent."""


class SkatReportRow(BaseModel):
    """One traceable line in the SKAT report."""

    model_config = ConfigDict(frozen=True)

    line_number: int = Field(..., ge=1)
    category: Category
    source_id: str = Field(..., min_length=1)
    account_id: str = Field(..., min_length=1)
    isin: str | None = None
    tax_year: int = Field(..., ge=1900, le=2999)
    gain: Money
    """Positive = taxable income, negative = deductible loss (DKK)."""

    tax_withheld: Money
    """Tax already withheld at source (e.g. PAL-skat from PFA)."""

    notes: str = ""

    @field_validator("gain", "tax_withheld")
    @classmethod
    def _dkk_only(cls, v: Money) -> Money:
        if v.currency != _DKK:
            raise SkatReportError(f"SkatReportRow amounts must be DKK, got {v.currency}")
        return v


@dataclass(frozen=True)
class SkatReport:
    """Aggregated SKAT report for one tax year."""

    tax_year: int
    rows: tuple[SkatReportRow, ...] = field(default_factory=tuple)
    prior_loss_carry_forward: Money = field(default_factory=lambda: _dkk(Decimal(0)))
    gross_capital_income: Money = field(default_factory=lambda: _dkk(Decimal(0)))
    """Sum of all ``gain`` rows, *before* applying prior-year carry-forward."""

    taxable_capital_income: Money = field(default_factory=lambda: _dkk(Decimal(0)))
    """``max(gross_capital_income - prior_loss_carry_forward, 0)``."""

    loss_carry_forward: Money = field(default_factory=lambda: _dkk(Decimal(0)))
    """Magnitude of unused loss to roll into the next tax year."""

    tax_withheld_total: Money = field(default_factory=lambda: _dkk(Decimal(0)))
    """Sum of taxes already paid at source (PAL etc.) in this year."""


def _row_lager(line: int, r: LagerResult) -> SkatReportRow:
    return SkatReportRow(
        line_number=line,
        category="lager",
        source_id=f"lager:{r.account_id}:{r.isin}",
        account_id=r.account_id,
        isin=r.isin,
        tax_year=r.tax_year,
        gain=r.gain,
        tax_withheld=_dkk(Decimal(0)),
        notes="Lagerbeskatning (mark-to-market) per ISIN",
    )


def _row_ask(line: int, r: AskTaxResult) -> SkatReportRow:
    return SkatReportRow(
        line_number=line,
        category="ask",
        source_id=f"ask:{r.account_id}",
        account_id=r.account_id,
        isin=None,
        tax_year=r.tax_year,
        # Note: ASK tax is settled via the account itself at 17 %,
        # not through the ordinary capital-income bands. We therefore
        # report the gross gain on its own line and treat tax_due as
        # already withheld so it is excluded from the taxable total.
        gain=r.gain,
        tax_withheld=r.tax_due,
        notes="Aktiesparekonto, 17 % settled via account",
    )


def _row_pal(line: int, r: PalResult) -> SkatReportRow:
    return SkatReportRow(
        line_number=line,
        category="pal",
        source_id=f"pal:{r.account_id}",
        account_id=r.account_id,
        isin=None,
        tax_year=r.tax_year,
        # PAL-skat is settled by the pension provider at PAL_RATE.
        # We surface the return on its own line for traceability but
        # mark the tax as withheld so it doesn't double-count in
        # kapitalindkomst.
        gain=r.return_amount,
        tax_withheld=r.tax_due,
        notes=f"PAL-skat ({PAL_RATE * 100}%) withheld by provider",
    )


def _row_realised(line: int, idx: int, r: RealisedGain) -> SkatReportRow:
    if r.gain.currency != _DKK:
        raise SkatReportError(f"RealisedGain at line {line} must be DKK, got {r.gain.currency}")
    return SkatReportRow(
        line_number=line,
        category="realised",
        source_id=f"realised:{r.account_id}:{r.isin}:{idx}",
        account_id=r.account_id,
        isin=r.isin,
        tax_year=r.event_date.year,
        gain=r.gain,
        tax_withheld=_dkk(Decimal(0)),
        notes=f"Realised gain on {r.event_date.isoformat()}",
    )


def build_skat_report(
    *,
    tax_year: int,
    lager_results: Iterable[LagerResult] = (),
    ask_results: Iterable[AskTaxResult] = (),
    pal_results: Iterable[PalResult] = (),
    realised_gains: Iterable[RealisedGain] = (),
    prior_loss_carry_forward: Money | None = None,
) -> SkatReport:
    """Aggregate Phase-3 calculator outputs into one SKAT report.

    Only entries matching ``tax_year`` are included. ``RealisedGain``
    is bucketed by ``event_date.year``.

    ``prior_loss_carry_forward`` defaults to 0 DKK. It is netted
    against the year's gross capital income (lager + realised only —
    ASK and PAL settle separately and do not interact with the
    ordinary capital-income bands).
    """
    if prior_loss_carry_forward is None:
        prior_loss_carry_forward = _dkk(Decimal(0))
    if prior_loss_carry_forward.currency != _DKK:
        raise SkatReportError(
            f"prior_loss_carry_forward must be DKK, got {prior_loss_carry_forward.currency}"
        )
    if prior_loss_carry_forward.amount < 0:
        raise SkatReportError("prior_loss_carry_forward must be non-negative")

    rows: list[SkatReportRow] = []
    line = 1

    for lr in lager_results:
        if lr.tax_year != tax_year:
            continue
        rows.append(_row_lager(line, lr))
        line += 1

    for ar in ask_results:
        if ar.tax_year != tax_year:
            continue
        rows.append(_row_ask(line, ar))
        line += 1

    for pr in pal_results:
        if pr.tax_year != tax_year:
            continue
        rows.append(_row_pal(line, pr))
        line += 1

    realised_idx = 0
    for rg in realised_gains:
        if rg.event_date.year != tax_year:
            continue
        rows.append(_row_realised(line, realised_idx, rg))
        line += 1
        realised_idx += 1

    # Only lager + realised feed the ordinary capital-income line.
    gross = sum(
        (row.gain.amount for row in rows if row.category in ("lager", "realised")),
        start=Decimal(0),
    )
    after_cf = gross - prior_loss_carry_forward.amount
    taxable = max(after_cf, Decimal(0))
    new_cf = -after_cf if after_cf < 0 else Decimal(0)

    withheld = sum(
        (row.tax_withheld.amount for row in rows),
        start=Decimal(0),
    )

    return SkatReport(
        tax_year=tax_year,
        rows=tuple(rows),
        prior_loss_carry_forward=prior_loss_carry_forward,
        gross_capital_income=_dkk(gross),
        taxable_capital_income=_dkk(taxable),
        loss_carry_forward=_dkk(new_cf),
        tax_withheld_total=_dkk(withheld),
    )


_CSV_HEADER: Final = (
    "line_number",
    "category",
    "source_id",
    "account_id",
    "isin",
    "tax_year",
    "gain_dkk",
    "tax_withheld_dkk",
    "notes",
)


def to_csv(report: SkatReport) -> str:
    """Render the report as a SKAT-shaped CSV (UTF-8, comma-delimited)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(_CSV_HEADER)
    for row in report.rows:
        w.writerow(
            [
                row.line_number,
                row.category,
                row.source_id,
                row.account_id,
                row.isin or "",
                row.tax_year,
                f"{row.gain.amount:.2f}",
                f"{row.tax_withheld.amount:.2f}",
                row.notes,
            ]
        )
    return buf.getvalue()


def to_markdown(report: SkatReport) -> str:
    """Render the report as a human-readable markdown summary."""
    lines: list[str] = []
    lines.append(f"# SKAT report — tax year {report.tax_year}")
    lines.append("")
    lines.append("## Lines")
    lines.append("")
    lines.append("| # | Category | Source | Account | ISIN | Gain (DKK) | Withheld (DKK) | Notes |")
    lines.append("|---|----------|--------|---------|------|-----------:|---------------:|-------|")
    for row in report.rows:
        lines.append(
            f"| {row.line_number} | {row.category} | `{row.source_id}` | "
            f"{row.account_id} | {row.isin or ''} | "
            f"{row.gain.amount:.2f} | {row.tax_withheld.amount:.2f} | {row.notes} |"
        )
    lines.append("")
    lines.append("## Totals (DKK)")
    lines.append("")
    lines.append(
        f"- Prior-year loss carry-forward applied: **{report.prior_loss_carry_forward.amount:.2f}**"
    )
    lines.append(
        f"- Gross capital income (lager + realised): **{report.gross_capital_income.amount:.2f}**"
    )
    lines.append(f"- Taxable capital income: **{report.taxable_capital_income.amount:.2f}**")
    lines.append(f"- Loss carry-forward to next year: **{report.loss_carry_forward.amount:.2f}**")
    lines.append(
        f"- Tax withheld at source (ASK + PAL): **{report.tax_withheld_total.amount:.2f}**"
    )
    lines.append("")
    return "\n".join(lines)
