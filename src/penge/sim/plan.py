"""Household plan orchestrator — end-to-end projection runner.

Wires together the cashflow engine, liquid depot, bridge, payout, and
Folkepension modules into a single top-level projection.

Design rationale: ``docs/decisions/0031-sim-household-plan.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import Literal, Protocol

import pydantic

from penge.sim._decimal_utils import to_decimal as _to_decimal
from penge.sim.cashflow import (
    CashflowConfig,
    CashflowProjection,
    ContributionRule,
    PensionAccrualRule,
    SalaryRule,
    project,
)
from penge.sim.liquid import (
    BridgeConfig,
    BridgeResult,
    LiquidDepotConfig,
    LiquidProjection,
    compute_bridge_pmt,
    project_liquid,
)
from penge.sim.payout import (
    PayoutConfig,
    PayoutProjection,
)
from penge.sim.registry import (
    ProjectionAuditRecord,
    build_standard_audit_record,
)
from penge.sim.spending import (
    HouseholdSpendingPlan,
    SpendingPhase,
    compute_spending,
)
from penge.sim.tax import (
    TaxConfig,
    apply_tax,
)
from penge.tax.dk.folkepension import (
    CivilStatus,
    FolkepensionConfig,
    FolkepensionResult,
    compute_folkepension,
    folkepension_age_for_year,
    folkepension_from_payout,
)

__all__ = [
    "BridgeTemplate",
    "EntityBridgeResult",
    "EntityFolkepensionResult",
    "FolkepensionTemplate",
    "HouseholdMember",
    "HouseholdPlan",
    "HouseholdProjectionResult",
    "PayoutTemplate",
    "ProjectionWarning",
    "SpendingYear",
    "project_household",
]


WarningCode = Literal[
    "bridge_account_not_found",
    "bridge_config_invalid",
    "bridge_nonpositive_balance",
    "payout_entity_cashflow_not_found",
]


class ProjectionWarning(pydantic.BaseModel):
    """A non-fatal anomaly emitted during :func:`project_household`.

    Args:
        code: Stable machine-readable identifier for the warning type.
        entity: The entity (member name or template entity) that triggered
            the warning.
        message: Human-readable description with additional context.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    code: WarningCode
    entity: str
    message: str


# ---------------------------------------------------------------------------
# Sub-configuration helpers
# ---------------------------------------------------------------------------


class _HasEntity(Protocol):
    """Protocol for template objects that carry an ``entity`` member name."""

    entity: str


class HouseholdMember(pydantic.BaseModel):
    """A member of the household for projection purposes.

    Args:
        name: Entity identifier (must match the ``entity`` values used in
            salary rules, contribution rules, pension accrual rules, and
            payout / Folkepension templates).
        birth_year: Calendar year of birth.
        jurisdiction: Tax jurisdiction — ``"DK"`` or ``"DE"``.
        retirement_year: Last calendar year the member is in employment
            (inclusive).  The following year is the first year of bridge or
            retirement income.
        public_pension_start_year: Calendar year when public pension
            (Folkepension or GRV) begins.  Once *any* member crosses this
            boundary the household phase advances to RETIREMENT.  ``None``
            means public pension is not modelled for this member — the
            household will not enter RETIREMENT phase based on this member's
            timeline.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    name: str
    birth_year: int
    jurisdiction: Literal["DK", "DE"]
    retirement_year: int
    public_pension_start_year: int | None = None

    @pydantic.model_validator(mode="after")
    def _validate(self) -> HouseholdMember:
        if (
            self.public_pension_start_year is not None
            and self.public_pension_start_year <= self.retirement_year
        ):
            raise ValueError(
                f"Member '{self.name}': public_pension_start_year "
                f"({self.public_pension_start_year}) must be after retirement_year "
                f"({self.retirement_year})"
            )
        return self


class BridgeTemplate(pydantic.BaseModel):
    """Bridge-phase drawdown configuration for one entity.

    The starting balance and cost basis are read from the
    :class:`~penge.sim.liquid.YearlyLiquidFlow` for ``bridge_start_year`` in
    the matching :class:`~penge.sim.liquid.LiquidProjection`; they must **not**
    be specified here.

    Args:
        entity: Entity identifier used in result labelling.
        liquid_account_id: The :attr:`~penge.sim.liquid.LiquidDepotConfig
            .account_id` of the liquid account that funds the bridge.  Must be
            present in :attr:`HouseholdPlan.liquid_configs`.
        bridge_start_year: Calendar year at which bridge drawdown begins.
            The closing balance and cost basis of the liquid account at the
            *end* of this year are used as the bridge starting balance.
            Typically the member's last year of employment
            (``HouseholdMember.retirement_year``).
        horizon_months: Bridge duration in months.  Must be a multiple of
            12 when ``tax_regime='lager'``.
        gross_annual_return_rate: Expected gross total return during drawdown
            (fraction, e.g. ``Decimal("0.08")``).
        annual_expense_ratio: Fund ÅOP during drawdown (fraction).
        account_type: ``"ask"`` or ``"frie_midler"``.
        tax_regime: ``"lager"`` or ``"realisation"``.
        aktieindkomst_threshold_dkk: Per-person progressive bracket threshold
            for the bridge start year.
        annual_dividend_yield: Dividend yield for distributing realisation
            funds; zero for accumulating instruments.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    entity: str
    liquid_account_id: str
    bridge_start_year: int
    horizon_months: int
    gross_annual_return_rate: Decimal
    annual_expense_ratio: Decimal
    account_type: Literal["ask", "frie_midler"]
    tax_regime: Literal["lager", "realisation"]
    aktieindkomst_threshold_dkk: Decimal
    annual_dividend_yield: Decimal = Decimal("0")

    @pydantic.field_validator(
        "gross_annual_return_rate",
        "annual_expense_ratio",
        "aktieindkomst_threshold_dkk",
        "annual_dividend_yield",
        mode="before",
    )
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return _to_decimal(v)


class PayoutTemplate(pydantic.BaseModel):
    """Pension payout configuration for one entity.

    The pension balance at retirement is derived automatically from the net
    cashflow projection at ``retirement_year`` in :func:`project_household`.

    Args:
        entity: Entity identifier (must appear in the cashflow projection).
        retirement_year: Calendar year at which the pension balance snapshot
            is taken.  Pass the member's last year of employment (i.e.
            ``HouseholdMember.retirement_year``).  The snapshot is taken at
            the *end* of this year, which is also the start of the first
            retirement year per :class:`HouseholdMember` semantics.
        retirement_age: Age at which payout begins (for documentation and
            validation inside :class:`~penge.sim.payout.PayoutConfig`).
        livrente_fraction: Share of pension balance allocated to lifelong
            Livrente (fraction of total balance).
        ratepension_fraction: Share allocated to fixed-term Ratepension.
            The remainder (``1 - livrente_fraction - ratepension_fraction``)
            becomes the Aldersforsikring lump sum.
        ratepension_years: Ratepension drawdown period in years (10-30).
        annuity_factor: Monthly gross payout per 1 000 000 units of Livrente
            capital (in the same currency as the pension balance).
        growth_rate_during_payout: Annual nominal return during Ratepension
            drawdown; defaults to ``0`` (level monthly payments).
    """

    model_config = pydantic.ConfigDict(frozen=True)

    entity: str
    retirement_year: int
    retirement_age: int
    livrente_fraction: Decimal
    ratepension_fraction: Decimal
    ratepension_years: int
    annuity_factor: Decimal
    growth_rate_during_payout: Decimal = Decimal("0")

    @pydantic.field_validator(
        "livrente_fraction",
        "ratepension_fraction",
        "annuity_factor",
        "growth_rate_during_payout",
        mode="before",
    )
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return _to_decimal(v)


class FolkepensionTemplate(pydantic.BaseModel):
    """DK Folkepension configuration for one entity.

    If a :class:`PayoutTemplate` exists for the same entity, its
    ``total_monthly_gross_eur`` is used as the private pension income base
    for means-testing; otherwise zero private income is assumed.

    Args:
        entity: Entity identifier.  Must appear in
            :attr:`HouseholdPlan.members` with ``jurisdiction="DK"``.
        civil_status: ``"single"`` or ``"married"``.  Determines the
            maximum pensionstillæg.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    entity: str
    civil_status: CivilStatus


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class EntityBridgeResult(pydantic.BaseModel):
    """Bridge-phase result for one entity.

    Args:
        entity: Entity identifier (from :class:`BridgeTemplate`).
        result: The underlying :class:`~penge.sim.liquid.BridgeResult`.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    entity: str
    result: BridgeResult


class EntityFolkepensionResult(pydantic.BaseModel):
    """DK Folkepension result for one entity.

    Args:
        entity: Entity identifier (from :class:`FolkepensionTemplate`).
        result: The underlying :class:`~penge.tax.dk.folkepension.FolkepensionResult`.
    """

    model_config = pydantic.ConfigDict(frozen=True, arbitrary_types_allowed=True)

    entity: str
    result: FolkepensionResult


class SpendingYear(pydantic.BaseModel):
    """Computed household spending totals for one projected year.

    Args:
        year: Calendar year.
        phase: FIRE lifecycle phase in this year.
        total_eur: Total annual spending in EUR for this year and phase.
        total_dkk: Total annual spending in DKK for this year and phase.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    year: int
    phase: SpendingPhase
    total_eur: Decimal
    total_dkk: Decimal


class HouseholdProjectionResult(pydantic.BaseModel):
    """Full output of :func:`project_household`.

    Args:
        plan: The :class:`HouseholdPlan` that produced this result.
        cashflow_gross: Gross (pre-tax) cashflow projection.
        cashflow_net: Net (post-tax) cashflow projection.
        liquid_projections: Liquid depot projections, one per entry in
            :attr:`HouseholdPlan.liquid_configs`.
        bridge_results: Bridge-phase drawdown results, one per successfully
            computed :class:`BridgeTemplate`.
        payout_projections: Pension payout projections, one per successfully
            computed :class:`PayoutTemplate`.
        folkepension_results: DK Folkepension results, one per
            :class:`FolkepensionTemplate`.
        spending_by_year: Spending totals per projected calendar year.
        audit_record: Standard assumption audit record.
        warnings: Human-readable warnings (e.g. missing account references
            or zero terminal balances).  An empty tuple indicates no
            anomalies were detected.
    """

    model_config = pydantic.ConfigDict(frozen=True, arbitrary_types_allowed=True)

    plan: HouseholdPlan
    cashflow_gross: CashflowProjection
    cashflow_net: CashflowProjection
    liquid_projections: tuple[LiquidProjection, ...]
    bridge_results: tuple[EntityBridgeResult, ...]
    payout_projections: tuple[PayoutProjection, ...]
    folkepension_results: tuple[EntityFolkepensionResult, ...]
    spending_by_year: tuple[SpendingYear, ...]
    audit_record: ProjectionAuditRecord
    warnings: tuple[ProjectionWarning, ...]


# ---------------------------------------------------------------------------
# Top-level plan
# ---------------------------------------------------------------------------


class HouseholdPlan(pydantic.BaseModel):
    """Top-level household planning configuration.

    Wires together all sub-module configurations into a single plan that
    :func:`project_household` can execute in one call.

    Args:
        base_year: Starting calendar year (year 0; first projected year is
            ``base_year + 1``).
        horizon_years: Number of years to project (≥ 1).
        inflation_rate: Annual CPI growth rate (fraction).
        eur_per_dkk: EUR per 1 DKK (from the ECB FX service).
        pension_market_return_rate: Annual gross market return on the pension
            balance (fraction).  Defaults to ``0`` (accruals only).
        pal_skat_rate: DK pension investment tax rate
            (``0.153`` for the standard rate; ``0`` to disable).
        members: Household members with retirement targets.  Must be
            non-empty.
        salaries: Salary streams per entity.
        contributions: Liquid investment contributions per entity.
        pension_rules: Pension accrual rules per entity.
        pension_opening_balances: Opening pension balance per entity in EUR.
            Entities not listed default to ``0``.
        tax_config: Tax configuration for computing net cashflow.
        spending_plan: Household spending rules and one-off expenses.
        liquid_configs: Liquid investment account configurations.
        bridge_templates: Bridge-phase drawdown configurations.
        payout_templates: Pension payout configurations.
        folkepension_templates: DK Folkepension configurations.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    base_year: int
    horizon_years: int
    inflation_rate: Decimal
    eur_per_dkk: Decimal
    pension_market_return_rate: Decimal = Decimal("0")
    pal_skat_rate: Decimal = Decimal("0")

    members: tuple[HouseholdMember, ...]
    salaries: tuple[SalaryRule, ...] = ()
    contributions: tuple[ContributionRule, ...] = ()
    pension_rules: tuple[PensionAccrualRule, ...] = ()
    pension_opening_balances: Mapping[str, Decimal] = pydantic.Field(
        default_factory=lambda: MappingProxyType({})
    )

    tax_config: TaxConfig = pydantic.Field(default_factory=TaxConfig)
    spending_plan: HouseholdSpendingPlan = pydantic.Field(
        default_factory=HouseholdSpendingPlan
    )

    liquid_configs: tuple[LiquidDepotConfig, ...] = ()
    bridge_templates: tuple[BridgeTemplate, ...] = ()
    payout_templates: tuple[PayoutTemplate, ...] = ()
    folkepension_templates: tuple[FolkepensionTemplate, ...] = ()

    @pydantic.field_validator(
        "inflation_rate",
        "eur_per_dkk",
        "pension_market_return_rate",
        "pal_skat_rate",
        mode="before",
    )
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return _to_decimal(v)

    @pydantic.field_validator("pension_opening_balances", mode="before")
    @classmethod
    def _coerce_opening_balances(cls, v: object) -> MappingProxyType[str, Decimal]:
        if v is None:
            return MappingProxyType({})
        if not isinstance(v, Mapping):
            raise ValueError("pension_opening_balances must be a mapping")
        return MappingProxyType({str(k): _to_decimal(val) for k, val in v.items()})

    @pydantic.model_validator(mode="after")
    def _validate(self) -> HouseholdPlan:
        if self.horizon_years < 1:
            raise ValueError("horizon_years must be >= 1")
        if self.eur_per_dkk <= 0:
            raise ValueError("eur_per_dkk must be positive")
        if not (Decimal("-0.5") <= self.inflation_rate <= Decimal("1")):
            raise ValueError("inflation_rate must be in [-0.5, 1.0]")
        if not (Decimal("0") <= self.pal_skat_rate < Decimal("1")):
            raise ValueError("pal_skat_rate must be in [0, 1)")
        self._validate_members()
        self._validate_liquid_configs()
        self._validate_templates()
        return self

    def _validate_members(self) -> None:
        if not self.members:
            raise ValueError("members must not be empty")
        names = [m.name for m in self.members]
        if len(names) != len(set(names)):
            dupes = {n for n in names if names.count(n) > 1}
            raise ValueError(f"Duplicate member names: {sorted(dupes)}")

    def _validate_liquid_configs(self) -> None:
        if len(self.liquid_configs) != len({c.account_id for c in self.liquid_configs}):
            raise ValueError("Duplicate liquid_configs account_id values")

    def _validate_templates(self) -> None:
        member_names = {m.name for m in self.members}
        self._check_template_entities("bridge_templates", self.bridge_templates, member_names)
        self._check_template_entities("payout_templates", self.payout_templates, member_names)
        self._check_folkepension_templates(member_names)

    def _check_template_entities(
        self,
        field: str,
        templates: tuple[_HasEntity, ...],
        member_names: set[str],
    ) -> None:
        entities: list[str] = []
        for tmpl in templates:
            if tmpl.entity not in member_names:
                raise ValueError(f"{field} entity '{tmpl.entity}' is not in members")
            entities.append(tmpl.entity)
        if len(entities) != len(set(entities)):
            raise ValueError(f"Duplicate {field} entities")

    def _check_folkepension_templates(self, member_names: set[str]) -> None:
        entities: list[str] = []
        for fp_tmpl in self.folkepension_templates:
            if fp_tmpl.entity not in member_names:
                raise ValueError(
                    f"FolkepensionTemplate entity '{fp_tmpl.entity}' is not in members"
                )
            member = next(m for m in self.members if m.name == fp_tmpl.entity)
            if member.jurisdiction != "DK":
                raise ValueError(
                    f"FolkepensionTemplate entity '{fp_tmpl.entity}' has jurisdiction "
                    f"'{member.jurisdiction}'; Folkepension only applies to DK members"
                )
            if member.public_pension_start_year is None:
                raise ValueError(
                    f"FolkepensionTemplate entity '{fp_tmpl.entity}' has no "
                    f"public_pension_start_year; set it to determine the correct "
                    f"statutory folkepensionsalder"
                )
            entities.append(fp_tmpl.entity)
        if len(entities) != len(set(entities)):
            raise ValueError("Duplicate folkepension_templates entities")


# ---------------------------------------------------------------------------
# Phase helper
# ---------------------------------------------------------------------------


def _household_phase(year: int, plan: HouseholdPlan) -> SpendingPhase:
    """Return the FIRE phase for the household in *year*.

    - ACCUMULATION: any member is still in employment (year <= max retirement_year)
    - RETIREMENT: any member's public pension has started
      (year >= earliest public_pension_start_year across all members)
    - BRIDGE: the gap between the two

    Note on multi-member edge cases:
        The RETIREMENT threshold is the *earliest* ``public_pension_start_year``
        across all members.  If that year precedes another member's
        ``retirement_year``, the phase sequence will jump directly from
        ACCUMULATION to RETIREMENT (no BRIDGE phase).
        This is intentional: the household spending mix shifts as soon as
        *any* member's public pension starts, even if another member has not
        yet retired.  Callers who need per-member phase granularity should
        inspect the individual ``HouseholdMember`` fields directly.
    """
    max_retirement = max(m.retirement_year for m in plan.members)
    if year <= max_retirement:
        return SpendingPhase.ACCUMULATION

    pension_years = [
        m.public_pension_start_year
        for m in plan.members
        if m.public_pension_start_year is not None
    ]
    if pension_years and year >= min(pension_years):
        return SpendingPhase.RETIREMENT

    return SpendingPhase.BRIDGE


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def project_household(plan: HouseholdPlan) -> HouseholdProjectionResult:
    """Execute a full end-to-end household projection.

    Composes the cashflow, liquid depot, bridge, payout, Folkepension, and
    spending modules using the configuration in *plan*.  Every section is
    deterministic given the same *plan* inputs.

    Args:
        plan: Fully configured :class:`HouseholdPlan`.

    Returns:
        :class:`HouseholdProjectionResult` with all computed sections.
        Non-fatal anomalies (e.g. a bridge template referencing an unknown
        liquid account) are reported in
        :attr:`~HouseholdProjectionResult.warnings` rather than raised.
    """
    warnings: list[ProjectionWarning] = []

    # ---- 1. Cashflow projection ----
    cf_config = CashflowConfig(
        base_year=plan.base_year,
        horizon_years=plan.horizon_years,
        inflation_rate=plan.inflation_rate,
        eur_per_dkk=plan.eur_per_dkk,
        salaries=plan.salaries,
        contributions=plan.contributions,
        pension_rules=plan.pension_rules,
        pension_opening_balances=plan.pension_opening_balances,
        pension_market_return_rate=plan.pension_market_return_rate,
        pal_skat_rate=plan.pal_skat_rate,
    )
    cashflow_gross = project(cf_config)
    cashflow_net = apply_tax(cashflow_gross, plan.tax_config)

    # ---- 2. Liquid depot projections ----
    liquid_projections = tuple(
        project_liquid(config, base_year=plan.base_year, horizon_years=plan.horizon_years)
        for config in plan.liquid_configs
    )
    liquid_by_account: dict[str, LiquidProjection] = {
        proj.config.account_id: proj for proj in liquid_projections
    }

    # ---- 3. Bridge-phase drawdown ----
    bridge_results: list[EntityBridgeResult] = []
    for tmpl in plan.bridge_templates:
        if tmpl.liquid_account_id not in liquid_by_account:
            warnings.append(ProjectionWarning(
                code="bridge_account_not_found",
                entity=tmpl.entity,
                message=(
                    f"BridgeTemplate for '{tmpl.entity}': liquid account "
                    f"'{tmpl.liquid_account_id}' not found in liquid_configs; skipping."
                ),
            ))
            continue
        liq = liquid_by_account[tmpl.liquid_account_id]
        bridge_flow = next(
            (f for f in liq.flows if f.year == tmpl.bridge_start_year), None
        )
        if bridge_flow is None:
            warnings.append(ProjectionWarning(
                code="bridge_account_not_found",
                entity=tmpl.entity,
                message=(
                    f"BridgeTemplate for '{tmpl.entity}': bridge_start_year "
                    f"{tmpl.bridge_start_year} not in liquid projection "
                    f"(base_year={plan.base_year}, horizon_years={plan.horizon_years}); skipping."
                ),
            ))
            continue
        bridge_balance = bridge_flow.closing_balance_dkk
        if bridge_balance <= Decimal("0"):
            warnings.append(ProjectionWarning(
                code="bridge_nonpositive_balance",
                entity=tmpl.entity,
                message=(
                    f"BridgeTemplate for '{tmpl.entity}': liquid account "
                    f"'{tmpl.liquid_account_id}' closing balance at {tmpl.bridge_start_year} "
                    f"is non-positive ({bridge_balance} DKK); skipping."
                ),
            ))
            continue
        try:
            bridge_cfg = BridgeConfig(
                starting_balance_dkk=bridge_balance,
                cost_basis_dkk=bridge_flow.cost_basis_dkk,
                horizon_months=tmpl.horizon_months,
                gross_annual_return_rate=tmpl.gross_annual_return_rate,
                annual_expense_ratio=tmpl.annual_expense_ratio,
                account_type=tmpl.account_type,
                tax_regime=tmpl.tax_regime,
                aktieindkomst_threshold_dkk=tmpl.aktieindkomst_threshold_dkk,
                annual_dividend_yield=tmpl.annual_dividend_yield,
            )
            bridge_results.append(
                EntityBridgeResult(entity=tmpl.entity, result=compute_bridge_pmt(bridge_cfg))
            )
        except (ValueError, pydantic.ValidationError) as exc:
            warnings.append(ProjectionWarning(
                code="bridge_config_invalid",
                entity=tmpl.entity,
                message=(
                    f"BridgeTemplate for '{tmpl.entity}': invalid bridge config: {exc}; skipping."
                ),
            ))

    # ---- 4. Pension payout ----
    payout_projections: list[PayoutProjection] = []
    payout_by_entity: dict[str, PayoutProjection] = {}
    for payout_tmpl in plan.payout_templates:
        dummy_payout_cfg = PayoutConfig(
            entity=payout_tmpl.entity,
            pension_balance_eur=Decimal("0"),  # overridden inside payout_at()
            retirement_age=payout_tmpl.retirement_age,
            livrente_fraction=payout_tmpl.livrente_fraction,
            ratepension_fraction=payout_tmpl.ratepension_fraction,
            ratepension_years=payout_tmpl.ratepension_years,
            annuity_factor=payout_tmpl.annuity_factor,
            growth_rate_during_payout=payout_tmpl.growth_rate_during_payout,
        )
        try:
            proj = cashflow_net.payout_at(payout_tmpl.retirement_year, dummy_payout_cfg)
        except KeyError as exc:
            warnings.append(ProjectionWarning(
                code="payout_entity_cashflow_not_found",
                entity=payout_tmpl.entity,
                message=f"PayoutTemplate for '{payout_tmpl.entity}': {exc}; skipping.",
            ))
            continue
        payout_projections.append(proj)
        payout_by_entity[payout_tmpl.entity] = proj

    # ---- 5. DK Folkepension ----
    folkepension_results: list[EntityFolkepensionResult] = []
    for fp_tmpl in plan.folkepension_templates:
        member = next(m for m in plan.members if m.name == fp_tmpl.entity)
        fp_age = folkepension_age_for_year(member.public_pension_start_year)  # type: ignore[arg-type]  # validated non-None in _check_folkepension_templates
        if fp_tmpl.entity in payout_by_entity:
            fp_result = folkepension_from_payout(
                payout_by_entity[fp_tmpl.entity],
                civil_status=fp_tmpl.civil_status,
                folkepension_age=fp_age,
                eur_per_dkk=plan.eur_per_dkk,
            )
        else:
            fp_result = compute_folkepension(
                FolkepensionConfig(
                    civil_status=fp_tmpl.civil_status,
                    folkepension_age=fp_age,
                    annual_private_pension_income_dkk=Decimal("0"),
                )
            )
        folkepension_results.append(
            EntityFolkepensionResult(entity=fp_tmpl.entity, result=fp_result)
        )

    # ---- 6. Spending by year ----
    spending_by_year_list: list[SpendingYear] = []
    for year in range(plan.base_year + 1, plan.base_year + plan.horizon_years + 1):
        phase = _household_phase(year, plan)
        amounts = compute_spending(plan.spending_plan, year, phase)
        spending_by_year_list.append(
            SpendingYear(
                year=year,
                phase=phase,
                total_eur=amounts["EUR"],
                total_dkk=amounts["DKK"],
            )
        )

    # ---- 7. Audit record ----
    audit_record = build_standard_audit_record()

    return HouseholdProjectionResult(
        plan=plan,
        cashflow_gross=cashflow_gross,
        cashflow_net=cashflow_net,
        liquid_projections=liquid_projections,
        bridge_results=tuple(bridge_results),
        payout_projections=tuple(payout_projections),
        folkepension_results=tuple(folkepension_results),
        spending_by_year=tuple(spending_by_year_list),
        audit_record=audit_record,
        warnings=tuple(warnings),
    )
