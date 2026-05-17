"""Real-estate and mortgage scenario projection for household plans."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Decimal

import pydantic

from penge.sim._decimal_utils import to_decimal as _to_decimal

__all__ = [
    "MortgageConfig",
    "PropertyAssetConfig",
    "RealEstateProjection",
    "RealEstateYear",
    "project_real_estate",
]

_TWO_DP = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)


class PropertyAssetConfig(pydantic.BaseModel):
    """Property asset configuration for a household plan.

    Args:
        property_id: Stable identifier used by mortgages and scenarios.
        label: Human-readable property label.
        owner_entity: Optional household member identifier.
        start_year: First projected year in which the household owns the property.
        value_dkk: Property value at ``start_year``.
        annual_value_growth_rate: Nominal property-value growth assumption.
        annual_recurring_cost_dkk: Ownership costs excluded from mortgage payments.
        purchase_cost_dkk: One-off purchase costs paid in ``start_year``.
        sale_year: Optional year where the property is sold and equity becomes liquid.
        sale_cost_rate: Selling costs as a fraction of market value.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    property_id: str
    label: str
    owner_entity: str | None = None
    start_year: int
    value_dkk: Decimal
    annual_value_growth_rate: Decimal = Decimal("0")
    annual_recurring_cost_dkk: Decimal = Decimal("0")
    purchase_cost_dkk: Decimal = Decimal("0")
    sale_year: int | None = None
    sale_cost_rate: Decimal = Decimal("0")

    @pydantic.field_validator(
        "value_dkk",
        "annual_value_growth_rate",
        "annual_recurring_cost_dkk",
        "purchase_cost_dkk",
        "sale_cost_rate",
        mode="before",
    )
    @classmethod
    def _coerce_decimal(cls, value: object) -> Decimal:
        return _to_decimal(value)

    @pydantic.model_validator(mode="after")
    def _validate(self) -> PropertyAssetConfig:
        if self.value_dkk <= Decimal("0"):
            raise ValueError("value_dkk must be > 0")
        if self.annual_recurring_cost_dkk < Decimal("0"):
            raise ValueError("annual_recurring_cost_dkk must be >= 0")
        if self.purchase_cost_dkk < Decimal("0"):
            raise ValueError("purchase_cost_dkk must be >= 0")
        if not (Decimal("-1") < self.annual_value_growth_rate < Decimal("1")):
            raise ValueError("annual_value_growth_rate must be in (-1, 1)")
        if not (Decimal("0") <= self.sale_cost_rate < Decimal("1")):
            raise ValueError("sale_cost_rate must be in [0, 1)")
        if self.sale_year is not None and self.sale_year < self.start_year:
            raise ValueError("sale_year must be >= start_year")
        return self


class MortgageConfig(pydantic.BaseModel):
    """Mortgage configuration linked to one property.

    The model is intentionally planning-grade: one fixed rate, one annual
    amortisation amount, and no refinancing schedule.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    mortgage_id: str
    property_id: str
    start_year: int
    principal_dkk: Decimal
    annual_interest_rate: Decimal
    annual_amortization_dkk: Decimal
    end_year: int | None = None

    @pydantic.field_validator(
        "principal_dkk",
        "annual_interest_rate",
        "annual_amortization_dkk",
        mode="before",
    )
    @classmethod
    def _coerce_decimal(cls, value: object) -> Decimal:
        return _to_decimal(value)

    @pydantic.model_validator(mode="after")
    def _validate(self) -> MortgageConfig:
        if self.principal_dkk < Decimal("0"):
            raise ValueError("principal_dkk must be >= 0")
        if self.annual_amortization_dkk < Decimal("0"):
            raise ValueError("annual_amortization_dkk must be >= 0")
        if not (Decimal("0") <= self.annual_interest_rate < Decimal("1")):
            raise ValueError("annual_interest_rate must be in [0, 1)")
        if self.end_year is not None and self.end_year < self.start_year:
            raise ValueError("end_year must be >= start_year")
        return self


class RealEstateYear(pydantic.BaseModel):
    """Yearly property, debt, cost, and sale-proceeds row."""

    model_config = pydantic.ConfigDict(frozen=True)

    year: int
    property_id: str
    property_value_dkk: Decimal
    mortgage_balance_dkk: Decimal
    home_equity_dkk: Decimal
    interest_paid_dkk: Decimal
    principal_paid_dkk: Decimal
    recurring_costs_dkk: Decimal
    purchase_cost_dkk: Decimal
    sale_proceeds_dkk: Decimal


class RealEstateProjection(pydantic.BaseModel):
    """Projection for one property and its optional mortgage."""

    model_config = pydantic.ConfigDict(frozen=True)

    property_config: PropertyAssetConfig
    mortgage: MortgageConfig | None
    rows: tuple[RealEstateYear, ...]

    @property
    def final_row(self) -> RealEstateYear:
        """Return the final projected row."""

        return self.rows[-1]


def project_real_estate(
    properties: tuple[PropertyAssetConfig, ...],
    mortgages: tuple[MortgageConfig, ...],
    *,
    base_year: int,
    horizon_years: int,
) -> tuple[RealEstateProjection, ...]:
    """Project property value, mortgage debt, costs, and sale proceeds."""

    if horizon_years < 1:
        raise ValueError("horizon_years must be >= 1")
    mortgage_by_property = _mortgages_by_property(mortgages)
    return tuple(
        _project_property(
            property_config,
            mortgage_by_property.get(property_config.property_id),
            base_year=base_year,
            horizon_years=horizon_years,
        )
        for property_config in properties
    )


def _project_property(
    property_config: PropertyAssetConfig,
    mortgage: MortgageConfig | None,
    *,
    base_year: int,
    horizon_years: int,
) -> RealEstateProjection:
    rows: list[RealEstateYear] = []
    mortgage_balance = Decimal("0")
    sale_has_happened = False
    for year in range(base_year + 1, base_year + horizon_years + 1):
        if mortgage is not None and year == mortgage.start_year:
            mortgage_balance = mortgage.principal_dkk

        active = property_config.start_year <= year and not sale_has_happened
        if not active:
            rows.append(_zero_row(year, property_config.property_id))
            continue

        market_value = _property_market_value(property_config, year)
        interest_paid = Decimal("0")
        principal_paid = Decimal("0")
        if mortgage is not None and _mortgage_active(mortgage, year):
            interest_paid = _q(mortgage_balance * mortgage.annual_interest_rate)
            principal_paid = min(mortgage.annual_amortization_dkk, mortgage_balance)
            mortgage_balance = _q(mortgage_balance - principal_paid)

        sale_proceeds = Decimal("0")
        property_value = market_value
        debt = mortgage_balance
        if property_config.sale_year == year:
            sale_cost = _q(market_value * property_config.sale_cost_rate)
            sale_proceeds = _q(max(market_value - sale_cost - mortgage_balance, Decimal("0")))
            property_value = Decimal("0")
            debt = Decimal("0")
            mortgage_balance = Decimal("0")
            sale_has_happened = True

        rows.append(
            RealEstateYear(
                year=year,
                property_id=property_config.property_id,
                property_value_dkk=_q(property_value),
                mortgage_balance_dkk=_q(debt),
                home_equity_dkk=_q(max(property_value - debt, Decimal("0"))),
                interest_paid_dkk=interest_paid,
                principal_paid_dkk=_q(principal_paid),
                recurring_costs_dkk=_q(property_config.annual_recurring_cost_dkk),
                purchase_cost_dkk=(
                    _q(property_config.purchase_cost_dkk)
                    if year == property_config.start_year
                    else Decimal("0")
                ),
                sale_proceeds_dkk=sale_proceeds,
            )
        )
    return RealEstateProjection(
        property_config=property_config,
        mortgage=mortgage,
        rows=tuple(rows),
    )


def _mortgages_by_property(
    mortgages: tuple[MortgageConfig, ...],
) -> Mapping[str, MortgageConfig]:
    by_property: dict[str, MortgageConfig] = {}
    for mortgage in mortgages:
        if mortgage.property_id in by_property:
            raise ValueError(f"duplicate mortgage for property_id {mortgage.property_id!r}")
        by_property[mortgage.property_id] = mortgage
    return by_property


def _property_market_value(property_config: PropertyAssetConfig, year: int) -> Decimal:
    elapsed_years = max(year - property_config.start_year, 0)
    return _q(
        property_config.value_dkk
        * ((Decimal("1") + property_config.annual_value_growth_rate) ** elapsed_years)
    )


def _mortgage_active(mortgage: MortgageConfig, year: int) -> bool:
    if year < mortgage.start_year:
        return False
    return mortgage.end_year is None or year <= mortgage.end_year


def _zero_row(year: int, property_id: str) -> RealEstateYear:
    return RealEstateYear(
        year=year,
        property_id=property_id,
        property_value_dkk=Decimal("0"),
        mortgage_balance_dkk=Decimal("0"),
        home_equity_dkk=Decimal("0"),
        interest_paid_dkk=Decimal("0"),
        principal_paid_dkk=Decimal("0"),
        recurring_costs_dkk=Decimal("0"),
        purchase_cost_dkk=Decimal("0"),
        sale_proceeds_dkk=Decimal("0"),
    )
