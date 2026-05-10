"""DE Vorabpauschale + Teilfreistellung calculator (issue #40).

Computes the German *Vorabpauschale* (deemed annual distribution) for
accumulating investment funds plus the *Teilfreistellung* exemption
quota that depends on the fund's classification under the
*Investmentsteuergesetz* (InvStG).

This module is the German counterpart to the Danish
:mod:`penge.tax.lager` calculator: pure functions, frozen Pydantic
models, EUR only.

Formula (per ISIN, per year):

.. code-block:: text

    basisertrag       = start_value × Basiszinssatz × 0.7 × (months / 12)
    vorabpauschale    = max(basisertrag − distributions, 0)
    vorabpauschale    = min(vorabpauschale, max(wertzuwachs, 0))   # cap
    taxable           = vorabpauschale × (1 − teilfreistellung_quote)
    tax               = taxable × ABGELT_RATE                       # 26.375 %

The Sparerpauschbetrag (€1 000 / year per taxpayer) is *not* applied
here — it is a household-level allowance that the SKAT report
generator's German counterpart applies at aggregation time. Likewise,
the Vorabpauschale only becomes a tax obligation when the fund is
sold; this module reports the *deemed annual amount* that adjusts the
cost basis. Persisting that running adjustment is the consumer's job.

Basiszins values follow the BMF publication and are exposed as the
``BASISZINS_DE`` constant table; negative or zero values short-circuit
the Vorabpauschale to 0 (this happened in 2021/2022).
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from penge.tax.lots import Money

__all__ = [
    "ABGELT_RATE",
    "BASISZINS_DE",
    "FundClassification",
    "TEILFREISTELLUNG_QUOTES",
    "VorabError",
    "VorabInput",
    "VorabResult",
    "compute_vorabpauschale",
    "compute_vorabpauschale_many",
    "to_markdown",
]

_MONEY_DP: Final = Decimal("0.01")
_EUR: Final[Literal["EUR"]] = "EUR"

ABGELT_RATE: Final = Decimal("0.26375")
"""Abgeltungsteuer 25 % + Solidaritätszuschlag 5.5 % thereon."""

BASISZINS_DE: Final[dict[int, Decimal]] = {
    2018: Decimal("0.0087"),
    2019: Decimal("0.0052"),
    2020: Decimal("0.0007"),
    2021: Decimal("-0.0045"),
    2022: Decimal("-0.0005"),
    2023: Decimal("0.0255"),
    2024: Decimal("0.0229"),
    2025: Decimal("0.0225"),
}
"""BMF-published Basiszins per tax year. Negative values are clamped
to zero by the Vorabpauschale formula (no Vorabpauschale in those
years)."""


FundClassification = Literal["equity", "mixed", "real_estate", "other"]

TEILFREISTELLUNG_QUOTES: Final[dict[FundClassification, Decimal]] = {
    "equity": Decimal("0.30"),
    "mixed": Decimal("0.15"),
    "real_estate": Decimal("0.60"),
    "other": Decimal("0.00"),
}
"""Teilfreistellung quotas per InvStG §20.

- ``equity`` — Aktienfonds with ≥51 % equity exposure: 30 %.
- ``mixed`` — Mischfonds with ≥25 % equity exposure: 15 %.
- ``real_estate`` — Immobilienfonds (≥51 % real estate): 60 %.
- ``other`` — everything else (bond funds etc.): 0 %.
"""


def _q(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_DP, rounding=ROUND_HALF_EVEN)


class VorabError(Exception):
    """Raised when a Vorabpauschale input is inconsistent."""


def _ensure_eur_nonneg(v: Money, *, label: str) -> Money:
    if v.currency != _EUR:
        raise VorabError(f"{label} must be EUR, got {v.currency}")
    if v.amount < 0:
        raise VorabError(f"{label} must be non-negative")
    return v


def _eur(amount: Decimal) -> Money:
    return Money(amount=_q(amount), currency=_EUR)


class VorabInput(BaseModel):
    """All data required to compute Vorabpauschale for one ISIN, one year."""

    model_config = ConfigDict(frozen=True)

    isin: str = Field(..., min_length=12, max_length=12)
    tax_year: int = Field(..., ge=1900, le=2999)
    classification: FundClassification
    start_value: Money
    end_value: Money
    distributions: Money = Field(default_factory=lambda: _eur(Decimal(0)))
    holding_months: int = Field(default=12, ge=1, le=12)

    @field_validator("start_value")
    @classmethod
    def _start_eur(cls, v: Money) -> Money:
        return _ensure_eur_nonneg(v, label="VorabInput.start_value")

    @field_validator("end_value")
    @classmethod
    def _end_eur(cls, v: Money) -> Money:
        return _ensure_eur_nonneg(v, label="VorabInput.end_value")

    @field_validator("distributions")
    @classmethod
    def _dist_eur(cls, v: Money) -> Money:
        return _ensure_eur_nonneg(v, label="VorabInput.distributions")


class VorabResult(BaseModel):
    """Per-ISIN, per-year Vorabpauschale + Abgeltungsteuer result in EUR."""

    model_config = ConfigDict(frozen=True)

    isin: str
    tax_year: int
    classification: FundClassification
    basiszins: Decimal
    """Basiszins applied for the tax year (already clamped at 0)."""

    basisertrag: Money
    """``start_value × basiszins × 0.7 × (months/12)``, the theoretical
    deemed yield."""

    wertzuwachs: Money
    """``end_value − start_value + distributions``; can be negative."""

    vorabpauschale: Money
    """The Vorabpauschale after netting distributions and capping at the
    actual fund increase. Always ≥ 0."""

    teilfreistellung_quote: Decimal
    """Exemption fraction applied (e.g. 0.30 for equity funds)."""

    taxable: Money
    """``vorabpauschale × (1 − teilfreistellung_quote)``."""

    tax_due: Money
    """``taxable × ABGELT_RATE``."""


def compute_vorabpauschale(inp: VorabInput) -> VorabResult:
    """Compute Vorabpauschale + Abgeltungsteuer for one ISIN, one year.

    Pure function: no I/O, no FX. ``inp.tax_year`` must be in
    :data:`BASISZINS_DE`; otherwise :class:`VorabError` is raised.
    """
    if inp.tax_year not in BASISZINS_DE:
        raise VorabError(
            f"No Basiszins on file for tax year {inp.tax_year}; " f"add it to BASISZINS_DE",
        )

    basiszins_raw = BASISZINS_DE[inp.tax_year]
    basiszins = max(basiszins_raw, Decimal(0))

    months_factor = Decimal(inp.holding_months) / Decimal(12)
    basisertrag_raw = inp.start_value.amount * basiszins * Decimal("0.7") * months_factor
    basisertrag = _q(basisertrag_raw)

    wertzuwachs_raw = inp.end_value.amount - inp.start_value.amount + inp.distributions.amount
    wertzuwachs = _q(wertzuwachs_raw)

    vp_after_dist = max(basisertrag - inp.distributions.amount, Decimal(0))
    vp_capped = min(vp_after_dist, max(wertzuwachs, Decimal(0)))
    vorabpauschale = _q(vp_capped)

    quote = TEILFREISTELLUNG_QUOTES[inp.classification]
    taxable = _q(vorabpauschale * (Decimal(1) - quote))
    tax_due = _q(taxable * ABGELT_RATE)

    return VorabResult(
        isin=inp.isin,
        tax_year=inp.tax_year,
        classification=inp.classification,
        basiszins=basiszins,
        basisertrag=_eur(basisertrag),
        wertzuwachs=_eur(wertzuwachs),
        vorabpauschale=_eur(vorabpauschale),
        teilfreistellung_quote=quote,
        taxable=_eur(taxable),
        tax_due=_eur(tax_due),
    )


def compute_vorabpauschale_many(
    inputs: Iterable[VorabInput],
) -> list[VorabResult]:
    """Convenience wrapper: map :func:`compute_vorabpauschale` over inputs."""
    return [compute_vorabpauschale(x) for x in inputs]


def to_markdown(results: Iterable[VorabResult]) -> str:
    """Render a markdown report for the Steuerberater."""
    rows = list(results)
    lines: list[str] = []
    lines.append("# Vorabpauschale-Bericht")
    lines.append("")
    if not rows:
        lines.append("_Keine Positionen._")
        return "\n".join(lines) + "\n"

    lines.append(
        "| ISIN | Jahr | Klasse | Basisertrag | Wertzuwachs | Vorab | TF % | Steuerpflichtig | Steuer |"
    )
    lines.append(
        "|------|-----:|--------|------------:|------------:|------:|-----:|----------------:|-------:|"
    )
    total_tax = Decimal(0)
    total_taxable = Decimal(0)
    for r in rows:
        lines.append(
            f"| {r.isin} | {r.tax_year} | {r.classification} | "
            f"{r.basisertrag.amount:.2f} | {r.wertzuwachs.amount:.2f} | "
            f"{r.vorabpauschale.amount:.2f} | {r.teilfreistellung_quote * 100:.0f} | "
            f"{r.taxable.amount:.2f} | {r.tax_due.amount:.2f} |"
        )
        total_tax += r.tax_due.amount
        total_taxable += r.taxable.amount

    lines.append("")
    lines.append("## Summen (EUR)")
    lines.append("")
    lines.append(f"- Steuerpflichtige Vorabpauschale: **{total_taxable:.2f}**")
    lines.append(f"- Abgeltungsteuer (26.375 %): **{total_tax:.2f}**")
    lines.append("")
    lines.append(
        "_Sparerpauschbetrag (€1 000) wird auf Haushaltsebene angewendet, "
        "nicht in diesem Bericht._"
    )
    return "\n".join(lines) + "\n"
