"""Household tax-event timeline derived from projection outputs."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

import pydantic

from penge.sim.plan import HouseholdProjectionResult
from penge.tax.dk.rates import DK_TOPSKAT_RATE, DK_TOPSKAT_THRESHOLD_DKK

__all__ = [
    "TaxAttribution",
    "TaxTimeline",
    "TaxTimelineRow",
    "TaxTimelineTotals",
    "TaxTimelineWarning",
    "build_tax_timeline",
]

_TWO_DP = Decimal("0.01")
_MATERIAL_CHANGE_ABS_DKK = Decimal("10000")
_MATERIAL_CHANGE_RATIO = Decimal("0.20")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)


class TaxAttribution(pydantic.BaseModel):
    """Account-level tax attribution for one timeline year."""

    model_config = pydantic.ConfigDict(frozen=True)

    source: str
    account_id: str
    account_type: str
    tax_regime: str
    tax_due_dkk: Decimal
    dividend_tax_dkk: Decimal = Decimal("0")
    withdrawal_tax_dkk: Decimal = Decimal("0")


class TaxTimelineWarning(pydantic.BaseModel):
    """Non-fatal timeline warning for material tax changes."""

    model_config = pydantic.ConfigDict(frozen=True)

    code: str
    year: int
    message: str


class TaxTimelineRow(pydantic.BaseModel):
    """Yearly tax and public-pension event row."""

    model_config = pydantic.ConfigDict(frozen=True)

    year: int
    pal_skat_dkk: Decimal
    ask_tax_dkk: Decimal
    frie_midler_aktieindkomst_tax_dkk: Decimal
    dividend_tax_dkk: Decimal
    bridge_withdrawal_tax_dkk: Decimal
    bridge_lager_tax_dkk: Decimal
    topskat_exposure_dkk: Decimal
    estimated_topskat_dkk: Decimal
    folkepension_modregning_dkk: Decimal
    total_tax_drag_dkk: Decimal
    attributions: tuple[TaxAttribution, ...] = ()
    warnings: tuple[TaxTimelineWarning, ...] = ()


class TaxTimelineTotals(pydantic.BaseModel):
    """Totals by tax type across the timeline."""

    model_config = pydantic.ConfigDict(frozen=True)

    pal_skat_dkk: Decimal
    ask_tax_dkk: Decimal
    frie_midler_aktieindkomst_tax_dkk: Decimal
    dividend_tax_dkk: Decimal
    bridge_withdrawal_tax_dkk: Decimal
    bridge_lager_tax_dkk: Decimal
    estimated_topskat_dkk: Decimal
    folkepension_modregning_dkk: Decimal
    total_tax_drag_dkk: Decimal


class TaxTimeline(pydantic.BaseModel):
    """Full household tax-event timeline."""

    model_config = pydantic.ConfigDict(frozen=True)

    rows: tuple[TaxTimelineRow, ...]
    totals: TaxTimelineTotals
    warnings: tuple[TaxTimelineWarning, ...]


def build_tax_timeline(result: HouseholdProjectionResult) -> TaxTimeline:
    """Build a yearly household tax-event timeline from a projection result."""

    rows: list[TaxTimelineRow] = []
    previous_total: Decimal | None = None
    start_year = result.plan.base_year + 1
    end_year = result.plan.base_year + result.plan.horizon_years + 1
    for year in range(start_year, end_year):
        attributions: list[TaxAttribution] = []
        ask_tax = Decimal("0")
        frie_tax = Decimal("0")
        dividend_tax = Decimal("0")
        for projection in result.liquid_projections:
            flow = next((item for item in projection.flows if item.year == year), None)
            if flow is None:
                continue
            tax_due = flow.tax_due_dkk
            liquid_dividend_tax = (
                tax_due
                if projection.config.tax_regime == "realisation"
                and projection.config.annual_dividend_yield > Decimal("0")
                else Decimal("0")
            )
            if projection.config.account_type == "ask":
                ask_tax += tax_due
            else:
                frie_tax += tax_due
            dividend_tax += liquid_dividend_tax
            if tax_due > Decimal("0"):
                attributions.append(
                    TaxAttribution(
                        source="liquid",
                        account_id=projection.config.account_id,
                        account_type=projection.config.account_type,
                        tax_regime=projection.config.tax_regime,
                        tax_due_dkk=_q(tax_due),
                        dividend_tax_dkk=_q(liquid_dividend_tax),
                    )
                )

        bridge_withdrawal_tax, bridge_lager_tax, bridge_dividend_tax, bridge_attributions = (
            _bridge_taxes_for_year(result, year)
        )
        attributions.extend(bridge_attributions)
        dividend_tax += bridge_dividend_tax

        pal_skat = _pal_skat_for_year(result, year)
        topskat_exposure = _topskat_exposure_for_year(result, year)
        estimated_topskat = _q(topskat_exposure * DK_TOPSKAT_RATE)
        folkepension_modregning = _folkepension_modregning_for_year(result, year)
        total_tax_drag = _q(
            pal_skat
            + ask_tax
            + frie_tax
            + bridge_withdrawal_tax
            + bridge_lager_tax
            + bridge_dividend_tax
            + estimated_topskat
            + folkepension_modregning
        )
        warnings = _warnings_for_row(
            year=year,
            total_tax_drag=total_tax_drag,
            previous_total=previous_total,
            topskat_exposure=topskat_exposure,
            folkepension_modregning=folkepension_modregning,
        )
        previous_total = total_tax_drag
        rows.append(
            TaxTimelineRow(
                year=year,
                pal_skat_dkk=_q(pal_skat),
                ask_tax_dkk=_q(ask_tax),
                frie_midler_aktieindkomst_tax_dkk=_q(frie_tax),
                dividend_tax_dkk=_q(dividend_tax),
                bridge_withdrawal_tax_dkk=_q(bridge_withdrawal_tax),
                bridge_lager_tax_dkk=_q(bridge_lager_tax),
                topskat_exposure_dkk=_q(topskat_exposure),
                estimated_topskat_dkk=estimated_topskat,
                folkepension_modregning_dkk=_q(folkepension_modregning),
                total_tax_drag_dkk=total_tax_drag,
                attributions=tuple(attributions),
                warnings=warnings,
            )
        )

    all_warnings = tuple(warning for row in rows for warning in row.warnings)
    return TaxTimeline(rows=tuple(rows), totals=_totals(rows), warnings=all_warnings)


def _pal_skat_for_year(result: HouseholdProjectionResult, year: int) -> Decimal:
    if result.plan.pal_skat_rate <= Decimal("0"):
        return Decimal("0")
    gross_factor = Decimal("1") - result.plan.pal_skat_rate
    if gross_factor <= Decimal("0"):
        return Decimal("0")
    tax = Decimal("0")
    for flow in result.cashflow_gross.flows:
        if flow.year != year or flow.pension_balance_growth_eur <= Decimal("0"):
            continue
        gross_growth_eur = flow.pension_balance_growth_eur / gross_factor
        pal_eur = gross_growth_eur - flow.pension_balance_growth_eur
        tax += pal_eur / result.plan.eur_per_dkk
    return _q(tax)


def _bridge_taxes_for_year(
    result: HouseholdProjectionResult,
    year: int,
) -> tuple[Decimal, Decimal, Decimal, tuple[TaxAttribution, ...]]:
    templates = {template.entity: template for template in result.plan.bridge_templates}
    withdrawal_tax = Decimal("0")
    lager_tax = Decimal("0")
    dividend_tax = Decimal("0")
    attributions: list[TaxAttribution] = []
    for entity_result in result.bridge_results:
        template = templates[entity_result.entity]
        yearly_flows = [
            flow
            for flow in entity_result.result.monthly_flows
            if template.bridge_start_year + ((flow.month - 1) // 12) + 1 == year
        ]
        if not yearly_flows:
            continue
        yearly_withdrawal = sum((flow.withdrawal_tax_dkk for flow in yearly_flows), Decimal("0"))
        yearly_lager = sum((flow.lager_tax_dkk for flow in yearly_flows), Decimal("0"))
        yearly_dividend = sum((flow.dividend_tax_dkk for flow in yearly_flows), Decimal("0"))
        withdrawal_tax += yearly_withdrawal
        lager_tax += yearly_lager
        dividend_tax += yearly_dividend
        total = yearly_withdrawal + yearly_lager + yearly_dividend
        if total > Decimal("0"):
            attributions.append(
                TaxAttribution(
                    source="bridge",
                    account_id=template.liquid_account_id,
                    account_type=template.account_type,
                    tax_regime=template.tax_regime,
                    tax_due_dkk=_q(total),
                    dividend_tax_dkk=_q(yearly_dividend),
                    withdrawal_tax_dkk=_q(yearly_withdrawal),
                )
            )
    return _q(withdrawal_tax), _q(lager_tax), _q(dividend_tax), tuple(attributions)


def _topskat_exposure_for_year(result: HouseholdProjectionResult, year: int) -> Decimal:
    exposure = Decimal("0")
    dk_members = {member.name for member in result.plan.members if member.jurisdiction == "DK"}
    for flow in result.cashflow_gross.flows:
        if flow.year == year and flow.entity in dk_members:
            salary_dkk = flow.gross_salary_eur / result.plan.eur_per_dkk
            exposure += max(salary_dkk - DK_TOPSKAT_THRESHOLD_DKK, Decimal("0"))
    return _q(exposure)


def _folkepension_modregning_for_year(result: HouseholdProjectionResult, year: int) -> Decimal:
    start_year_by_entity = {
        member.name: member.public_pension_start_year
        for member in result.plan.members
        if member.public_pension_start_year is not None
    }
    modregning = Decimal("0")
    for fp_result in result.folkepension_results:
        start_year = start_year_by_entity.get(fp_result.entity)
        if start_year is not None and year >= start_year:
            modregning += fp_result.result.modregning_dkk * Decimal("12")
    return _q(modregning)


def _warnings_for_row(
    *,
    year: int,
    total_tax_drag: Decimal,
    previous_total: Decimal | None,
    topskat_exposure: Decimal,
    folkepension_modregning: Decimal,
) -> tuple[TaxTimelineWarning, ...]:
    warnings: list[TaxTimelineWarning] = []
    if topskat_exposure > Decimal("0"):
        warnings.append(
            TaxTimelineWarning(
                code="topskat_exposure",
                year=year,
                message=f"DK income exceeds Topskat threshold by {_q(topskat_exposure)} DKK.",
            )
        )
    if folkepension_modregning > Decimal("0"):
        warnings.append(
            TaxTimelineWarning(
                code="folkepension_modregning",
                year=year,
                message=(
                    "Folkepension pension supplement is reduced by "
                    f"{_q(folkepension_modregning)} DKK/year."
                ),
            )
        )
    if previous_total is not None and previous_total > Decimal("0"):
        delta = abs(total_tax_drag - previous_total)
        if delta >= _MATERIAL_CHANGE_ABS_DKK and delta / previous_total >= _MATERIAL_CHANGE_RATIO:
            warnings.append(
                TaxTimelineWarning(
                    code="material_tax_drag_change",
                    year=year,
                    message=(f"Total tax drag changes by {_q(delta)} DKK versus the prior year."),
                )
            )
    return tuple(warnings)


def _totals(rows: list[TaxTimelineRow]) -> TaxTimelineTotals:
    return TaxTimelineTotals(
        pal_skat_dkk=_q(sum((row.pal_skat_dkk for row in rows), Decimal("0"))),
        ask_tax_dkk=_q(sum((row.ask_tax_dkk for row in rows), Decimal("0"))),
        frie_midler_aktieindkomst_tax_dkk=_q(
            sum((row.frie_midler_aktieindkomst_tax_dkk for row in rows), Decimal("0"))
        ),
        dividend_tax_dkk=_q(sum((row.dividend_tax_dkk for row in rows), Decimal("0"))),
        bridge_withdrawal_tax_dkk=_q(
            sum((row.bridge_withdrawal_tax_dkk for row in rows), Decimal("0"))
        ),
        bridge_lager_tax_dkk=_q(sum((row.bridge_lager_tax_dkk for row in rows), Decimal("0"))),
        estimated_topskat_dkk=_q(sum((row.estimated_topskat_dkk for row in rows), Decimal("0"))),
        folkepension_modregning_dkk=_q(
            sum((row.folkepension_modregning_dkk for row in rows), Decimal("0"))
        ),
        total_tax_drag_dkk=_q(sum((row.total_tax_drag_dkk for row in rows), Decimal("0"))),
    )
