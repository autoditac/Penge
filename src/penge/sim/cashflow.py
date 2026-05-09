"""Deterministic cashflow projection engine.

All monetary amounts are produced in **EUR**.  Inputs in DKK are converted
using the *eur_per_dkk* rate stored in :class:`CashflowConfig` — a scenario
assumption that the caller is expected to seed from the ECB FX service before
constructing the config.

The engine models three streams per entity per year:

- **Gross salary** — compounded by inflation + optional real wage growth.
- **Liquid contribution** — savings directed into the liquid investment portfolio
  (e.g. Nordnet deposits), optionally inflation-indexed.
- **Pension accrual** — either a defined-contribution fraction of gross salary
  (e.g. PFA 21 %) or a fixed annual EUR increment
  (e.g. Beamtenpension Bestandsfortschreibung).

Tax netting is **not** performed here.  See :mod:`penge.sim.tax_overlay` (#28)
for net-salary and effective-rate modelling.

Design rationale: `docs/decisions/0011-sim-cashflow-engine.md`.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal

import pydantic

__all__ = [
    "CashflowConfig",
    "CashflowError",
    "CashflowProjection",
    "ContributionRule",
    "PensionAccrualRule",
    "SalaryRule",
    "YearlyFlow",
    "project",
]


class CashflowError(Exception):
    """Raised when the cashflow config is internally inconsistent."""


_TWO_DP = Decimal("0.01")


def _to_decimal(v: object) -> Decimal:
    return Decimal(str(v))


def _compound(base: Decimal, rate: Decimal, periods: int) -> Decimal:
    """Return ``base * (1 + rate)^periods``, rounded to 2 decimal places."""
    return (base * (Decimal("1") + rate) ** periods).quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)


class SalaryRule(pydantic.BaseModel):
    """Salary stream that grows with inflation plus optional real wage growth.

    Args:
        entity: Identifier for the person/entity (e.g. ``"rouven"``).
        currency: Currency the *gross_annual* amount is expressed in.
        gross_annual: Base-year gross salary in *currency*.
        real_wage_growth: Annual real wage growth above CPI (fraction,
            e.g. ``Decimal("0.01")`` for 1 %).
    """

    model_config = pydantic.ConfigDict(frozen=True)

    entity: str
    currency: Literal["EUR", "DKK"] = "EUR"
    gross_annual: Decimal
    real_wage_growth: Decimal = Decimal("0")

    @pydantic.field_validator("gross_annual", "real_wage_growth", mode="before")
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return _to_decimal(v)

    @pydantic.model_validator(mode="after")
    def _positive_salary(self) -> SalaryRule:
        if self.gross_annual <= 0:
            raise ValueError("gross_annual must be positive")
        return self


class ContributionRule(pydantic.BaseModel):
    """Regular savings directed into the liquid investment portfolio.

    Args:
        entity: Identifier for the person/entity.
        currency: Currency the *annual* amount is expressed in.
        annual: Base-year annual contribution in *currency*.
        index_to_inflation: If ``True``, the amount is compounded by CPI
            each year; otherwise it is held constant in nominal terms.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    entity: str
    currency: Literal["EUR", "DKK"] = "EUR"
    annual: Decimal
    index_to_inflation: bool = True

    @pydantic.field_validator("annual", mode="before")
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return _to_decimal(v)

    @pydantic.model_validator(mode="after")
    def _positive_annual(self) -> ContributionRule:
        if self.annual <= 0:
            raise ValueError("annual must be positive")
        return self


class PensionAccrualRule(pydantic.BaseModel):
    """How a pension entitlement accrues each year.

    Two kinds:

    - ``dc_fraction``: Defined-contribution fraction of the entity's gross
      salary.  Suitable for PFA (combined employer + employee rate).
    - ``annual_eur``: Fixed annual accrual expressed in EUR, optionally
      inflation-indexed.  Suitable for Beamtenpension Bestandsfortschreibung.

    Args:
        entity: Identifier for the person/entity.
        kind: Accrual kind — ``"dc_fraction"`` or ``"annual_eur"``.
        dc_fraction: Required when *kind* is ``"dc_fraction"``.  Combined
            employer + employee contribution rate as a fraction of gross salary
            (e.g. ``Decimal("0.21")`` for PFA 21 %).
        annual_eur: Required when *kind* is ``"annual_eur"``.  New pension
            entitlement added each year, in EUR at the base year price level.
        index_accrual_to_inflation: When *kind* is ``"annual_eur"``, scale the
            annual accrual by CPI each year.  Default ``True``.
        vesting_year: Calendar year from which this pension can first be drawn.
            Informational here; consumed by the goal model (#30).
    """

    model_config = pydantic.ConfigDict(frozen=True)

    entity: str
    kind: Literal["dc_fraction", "annual_eur"]
    dc_fraction: Decimal | None = None
    annual_eur: Decimal | None = None
    index_accrual_to_inflation: bool = True
    vesting_year: int

    @pydantic.field_validator("dc_fraction", "annual_eur", mode="before")
    @classmethod
    def _coerce_opt(cls, v: object) -> Decimal | None:
        if v is None:
            return None
        return _to_decimal(v)

    @pydantic.model_validator(mode="after")
    def _validate_kind(self) -> PensionAccrualRule:
        if self.kind == "dc_fraction":
            if self.dc_fraction is None:
                raise ValueError("dc_fraction is required when kind='dc_fraction'")
            if not (Decimal("0") < self.dc_fraction <= Decimal("1")):
                raise ValueError("dc_fraction must be in (0, 1]")
        else:  # annual_eur
            if self.annual_eur is None:
                raise ValueError("annual_eur is required when kind='annual_eur'")
            if self.annual_eur <= 0:
                raise ValueError("annual_eur must be positive")
        return self


class CashflowConfig(pydantic.BaseModel):
    """Full configuration for a deterministic cashflow projection.

    Args:
        base_year: Starting calendar year (year 0; first projected year is
            ``base_year + 1``).
        horizon_years: Number of years to project.
        inflation_rate: Annual CPI growth rate (fraction, e.g. ``0.025``).
        eur_per_dkk: EUR per 1 DKK used to convert DKK inputs.  Source this
            from the ECB FX service before constructing the config.
        salaries: Salary streams per entity.
        contributions: Liquid investment contributions per entity.
        pension_rules: Pension accrual rules per entity.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    base_year: int
    horizon_years: int
    inflation_rate: Decimal
    eur_per_dkk: Decimal
    salaries: tuple[SalaryRule, ...]
    contributions: tuple[ContributionRule, ...]
    pension_rules: tuple[PensionAccrualRule, ...]

    @pydantic.field_validator("inflation_rate", "eur_per_dkk", mode="before")
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return _to_decimal(v)

    @pydantic.model_validator(mode="after")
    def _validate(self) -> CashflowConfig:
        if self.horizon_years < 1:
            raise ValueError("horizon_years must be >= 1")
        if not (Decimal("-0.5") <= self.inflation_rate <= Decimal("1")):
            raise ValueError("inflation_rate must be in [-0.5, 1.0]")
        if self.eur_per_dkk <= 0:
            raise ValueError("eur_per_dkk must be positive")
        return self


class YearlyFlow(pydantic.BaseModel):
    """Computed cashflow for one entity in one calendar year.

    Args:
        year: Calendar year.
        entity: Entity identifier.
        gross_salary_eur: Total gross salary in EUR for this year (all salary
            rules for this entity combined).
        liquid_contribution_eur: Amount directed into the liquid portfolio in
            EUR (all contribution rules for this entity combined).  Gross of
            taxes — see :mod:`penge.sim.tax_overlay` for net modelling.
        pension_accrual_eur: New pension entitlement accrued in this year.
        cumulative_pension_eur: Total pension entitlement accrued from the
            start of the projection through *year* (inclusive).
    """

    model_config = pydantic.ConfigDict(frozen=True)

    year: int
    entity: str
    gross_salary_eur: Decimal
    liquid_contribution_eur: Decimal
    pension_accrual_eur: Decimal
    cumulative_pension_eur: Decimal


class CashflowProjection(pydantic.BaseModel):
    """Output of :func:`project`: the full deterministic cashflow table.

    Args:
        config: The :class:`CashflowConfig` that produced this projection.
        flows: All per-entity per-year flows, in ascending year order.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    config: CashflowConfig
    flows: tuple[YearlyFlow, ...]

    def by_year(self, year: int) -> list[YearlyFlow]:
        """Return all entity flows for a given calendar year."""
        return [f for f in self.flows if f.year == year]

    def by_entity(self, entity: str) -> list[YearlyFlow]:
        """Return all yearly flows for a given entity."""
        return [f for f in self.flows if f.entity == entity]

    def entities(self) -> list[str]:
        """Sorted, deduplicated list of entity identifiers."""
        return sorted({f.entity for f in self.flows})

    def years(self) -> list[int]:
        """Sorted list of projected calendar years."""
        return sorted({f.year for f in self.flows})


def _compute_salaries(
    rules: tuple[SalaryRule, ...],
    entities: list[str],
    infl: Decimal,
    epd: Decimal,
    t_offset: int,
) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {e: Decimal("0") for e in entities}
    for s in rules:
        base_eur = s.gross_annual * (epd if s.currency == "DKK" else Decimal("1"))
        result[s.entity] += _compound(base_eur, infl + s.real_wage_growth, t_offset)
    return result


def _compute_contributions(
    rules: tuple[ContributionRule, ...],
    entities: list[str],
    infl: Decimal,
    epd: Decimal,
    t_offset: int,
) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {e: Decimal("0") for e in entities}
    for c in rules:
        base_eur = c.annual * (epd if c.currency == "DKK" else Decimal("1"))
        if c.index_to_inflation:
            result[c.entity] += _compound(base_eur, infl, t_offset)
        else:
            result[c.entity] += base_eur.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)
    return result


def _compute_pension_accruals(
    rules: tuple[PensionAccrualRule, ...],
    entities: list[str],
    salary_eur: dict[str, Decimal],
    infl: Decimal,
    t_offset: int,
) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {e: Decimal("0") for e in entities}
    for p in rules:
        if p.kind == "dc_fraction":
            # p.dc_fraction is guaranteed non-None by PensionAccrualRule validation
            fraction = p.dc_fraction if p.dc_fraction is not None else Decimal("0")
            accrual = (salary_eur[p.entity] * fraction).quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)
        else:
            # p.annual_eur is guaranteed non-None by PensionAccrualRule validation
            annual = p.annual_eur if p.annual_eur is not None else Decimal("0")
            if p.index_accrual_to_inflation:
                accrual = _compound(annual, infl, t_offset)
            else:
                accrual = annual.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)
        result[p.entity] += accrual
    return result


def project(config: CashflowConfig) -> CashflowProjection:
    """Run a deterministic year-by-year cashflow projection.

    For each year *t* in ``[base_year + 1, base_year + horizon_years]``:

    - **Salary**: compounded by ``(inflation_rate + real_wage_growth)`` each year
      relative to the base year.
    - **Liquid contributions**: compounded by ``inflation_rate`` if
      ``index_to_inflation`` is ``True``, otherwise held constant in nominal terms.
    - **Pension accruals**:

      - ``dc_fraction``: applied to that year's gross salary for the entity.
      - ``annual_eur``: compounded by ``inflation_rate`` if
        ``index_accrual_to_inflation`` is ``True``, otherwise held constant.

    DKK amounts are converted to EUR using ``config.eur_per_dkk``.

    Args:
        config: Projection configuration.

    Returns:
        A :class:`CashflowProjection` with one :class:`YearlyFlow` per entity
        per year.

    Raises:
        CashflowError: If a ``dc_fraction`` pension rule references an entity
            that has no salary rule (so the fraction cannot be computed).
    """
    salary_entities = {s.entity for s in config.salaries}
    for rule in config.pension_rules:
        if rule.kind == "dc_fraction" and rule.entity not in salary_entities:
            raise CashflowError(
                f"dc_fraction pension rule for '{rule.entity}' has no matching salary rule"
            )

    entities = sorted(
        {s.entity for s in config.salaries}
        | {c.entity for c in config.contributions}
        | {p.entity for p in config.pension_rules}
    )

    cumulative_pension: dict[str, Decimal] = {e: Decimal("0") for e in entities}
    flows: list[YearlyFlow] = []

    for t_offset in range(1, config.horizon_years + 1):
        year = config.base_year + t_offset
        infl = config.inflation_rate
        epd = config.eur_per_dkk

        salary_eur = _compute_salaries(config.salaries, entities, infl, epd, t_offset)
        contrib_eur = _compute_contributions(config.contributions, entities, infl, epd, t_offset)
        accrual_eur = _compute_pension_accruals(
            config.pension_rules, entities, salary_eur, infl, t_offset
        )

        for entity in entities:
            cumulative_pension[entity] += accrual_eur[entity]
            flows.append(
                YearlyFlow(
                    year=year,
                    entity=entity,
                    gross_salary_eur=salary_eur[entity],
                    liquid_contribution_eur=contrib_eur[entity],
                    pension_accrual_eur=accrual_eur[entity],
                    cumulative_pension_eur=cumulative_pension[entity],
                )
            )

    return CashflowProjection(config=config, flows=tuple(flows))
