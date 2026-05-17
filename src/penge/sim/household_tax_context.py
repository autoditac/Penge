"""Household-level DK/DE tax-context summary for planning reports."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

import pydantic

from penge.sim.plan import HouseholdPlan
from penge.sim.tax import EntityTaxRegime

__all__ = [
    "HouseholdTaxContext",
    "MemberTaxContext",
    "UnsupportedTaxFeature",
    "build_household_tax_context",
]

TaxCountry = Literal["DK", "DE"]


class UnsupportedTaxFeature(pydantic.BaseModel):
    """Unsupported or planning-grade tax area that must be visible to users."""

    model_config = pydantic.ConfigDict(frozen=True)

    member: str
    tax_country: TaxCountry
    code: str
    description: str
    next_action: str


class MemberTaxContext(pydantic.BaseModel):
    """Tax assumptions for one household member."""

    model_config = pydantic.ConfigDict(frozen=True)

    member: str
    jurisdiction: TaxCountry
    tax_country: TaxCountry
    salary_income_tax_rate: Decimal | None
    pension_return_tax_rate: Decimal | None
    pension_drawdown_tax_rate: Decimal | None
    capital_gains_effective_rate: Decimal | None
    supported_features: tuple[str, ...]
    unsupported_features: tuple[UnsupportedTaxFeature, ...]


class HouseholdTaxContext(pydantic.BaseModel):
    """Tax-country context for a household plan."""

    model_config = pydantic.ConfigDict(frozen=True)

    members: tuple[MemberTaxContext, ...]
    unsupported_features: tuple[UnsupportedTaxFeature, ...]


def build_household_tax_context(plan: HouseholdPlan) -> HouseholdTaxContext:
    """Summarize DK/DE tax contexts and unsupported assumptions for *plan*."""

    members: list[MemberTaxContext] = []
    unsupported: list[UnsupportedTaxFeature] = []
    for member in plan.members:
        tax_country = member.effective_tax_country
        regime = plan.tax_config.regimes.get(member.name)
        member_unsupported = _unsupported_features(member.name, tax_country)
        supported = _supported_features(tax_country, regime)
        context = MemberTaxContext(
            member=member.name,
            jurisdiction=member.jurisdiction,
            tax_country=tax_country,
            salary_income_tax_rate=_rate(regime, "salary_income_tax_rate"),
            pension_return_tax_rate=_rate(regime, "pension_return_tax_rate"),
            pension_drawdown_tax_rate=_rate(regime, "pension_drawdown_tax_rate"),
            capital_gains_effective_rate=_rate(regime, "capital_gains_effective_rate"),
            supported_features=supported,
            unsupported_features=member_unsupported,
        )
        members.append(context)
        unsupported.extend(member_unsupported)
    return HouseholdTaxContext(members=tuple(members), unsupported_features=tuple(unsupported))


def _rate(regime: EntityTaxRegime | None, field: str) -> Decimal | None:
    if regime is None:
        return None
    value = getattr(regime, field)
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be Decimal")
    return value


def _supported_features(
    tax_country: TaxCountry,
    regime: EntityTaxRegime | None,
) -> tuple[str, ...]:
    features = ["member-level tax-country context"]
    if regime is not None:
        features.append("effective salary tax overlay")
        features.append("effective pension drawdown tax rate")
        features.append("effective liquid capital-gains planning rate")
    if tax_country == "DK":
        features.append("PAL-skat planning rate")
        features.append("Folkepension means-test when configured")
        features.append("ASK/frie midler liquid-depot tax primitives")
    else:
        features.append("DE effective Abgeltungsteuer/Teilfreistellung planning rate")
    return tuple(features)


def _unsupported_features(
    member: str,
    tax_country: TaxCountry,
) -> tuple[UnsupportedTaxFeature, ...]:
    if tax_country == "DK":
        return ()
    return (
        UnsupportedTaxFeature(
            member=member,
            tax_country=tax_country,
            code="de_vorabpauschale_not_in_household_plan",
            description=(
                "DE depot planning uses an effective capital-gains rate; "
                "Vorabpauschale timing is not projected per fund in HouseholdPlan."
            ),
            next_action="Review docs/tax/de.md and model material Vorabpauschale separately.",
        ),
        UnsupportedTaxFeature(
            member=member,
            tax_country=tax_country,
            code="de_income_tax_brackets_not_modelled",
            description=(
                "DE salary and pension taxation use effective planning rates; "
                "Splittingtarif, Kirchensteuer, Soli, allowances, and exact "
                "Besteuerungsanteil are not computed here."
            ),
            next_action="Replace effective rates with tax-adviser outputs for filing decisions.",
        ),
    )
