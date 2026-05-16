"""Tests for penge.sim.plan — household plan orchestrator.

All fixtures use synthetic data only.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from penge.sim.cashflow import ContributionRule, PensionAccrualRule, SalaryRule
from penge.sim.liquid import LiquidDepotConfig
from penge.sim.plan import (
    BridgeTemplate,
    EntityBridgeResult,
    EntityFolkepensionResult,
    FolkepensionTemplate,
    HouseholdMember,
    HouseholdPlan,
    HouseholdProjectionResult,
    PayoutTemplate,
    ProjectionWarning,
    SpendingYear,
    _household_phase,
    project_household,
)
from penge.sim.spending import (
    HouseholdSpendingPlan,
    SpendingPhase,
    SpendingRule,
)
from penge.sim.tax import DE_DEFAULT, DK_DEFAULT, TaxConfig
from penge.tax.dk.folkepension import CivilStatus

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

BASE_YEAR = 2024
EUR_PER_DKK = Decimal("0.134")
_DE_BOB_BIRTH_YEAR = 1982
_DE_BOB_PUBLIC_PENSION_REFERENCE_YEAR = 2015
_DE_BOB_PUBLIC_PENSION_AGE = 67
_DE_BOB_PUBLIC_PENSION_START_YEAR = (
    _DE_BOB_PUBLIC_PENSION_REFERENCE_YEAR + _DE_BOB_PUBLIC_PENSION_AGE
)


def _dk_member(
    name: str = "alice",
    birth_year: int = 1980,
    retirement_year: int = 2055,
    public_pension_start_year: int | None = 2067,
) -> HouseholdMember:
    return HouseholdMember(
        name=name,
        birth_year=birth_year,
        jurisdiction="DK",
        retirement_year=retirement_year,
        public_pension_start_year=public_pension_start_year,
    )


def _de_member(
    name: str = "bob",
    birth_year: int = _DE_BOB_BIRTH_YEAR,
    retirement_year: int = 2050,
    public_pension_start_year: int | None = _DE_BOB_PUBLIC_PENSION_START_YEAR,
) -> HouseholdMember:
    return HouseholdMember(
        name=name,
        birth_year=birth_year,
        jurisdiction="DE",
        retirement_year=retirement_year,
        public_pension_start_year=public_pension_start_year,
    )


def _salary(
    entity: str,
    gross_annual: str = "60000",
    active_from: int | None = None,
    active_until: int | None = None,
) -> SalaryRule:
    return SalaryRule(
        entity=entity,
        gross_annual=Decimal(gross_annual),
        active_from=active_from,
        active_until=active_until,
    )


def _contribution(
    entity: str,
    annual: str = "6000",
    active_from: int | None = None,
    active_until: int | None = None,
) -> ContributionRule:
    return ContributionRule(
        entity=entity,
        annual=Decimal(annual),
        active_from=active_from,
        active_until=active_until,
    )


def _pension_rule(
    entity: str,
    dc_fraction: str = "0.15",
    vesting_year: int = 2060,
    active_from: int | None = None,
    active_until: int | None = None,
) -> PensionAccrualRule:
    return PensionAccrualRule(
        entity=entity,
        kind="dc_fraction",
        dc_fraction=Decimal(dc_fraction),
        vesting_year=vesting_year,
        active_from=active_from,
        active_until=active_until,
    )


def _ask_account(
    account_id: str = "alice-ask",
    opening_balance_dkk: str = "100000",
    annual_contribution_dkk: str = "20000",
) -> LiquidDepotConfig:
    return LiquidDepotConfig(
        account_id=account_id,
        account_type="ask",
        tax_regime="lager",
        opening_balance_dkk=Decimal(opening_balance_dkk),
        annual_contribution_dkk=Decimal(annual_contribution_dkk),
        gross_annual_return_rate=Decimal("0.08"),
        annual_expense_ratio=Decimal("0.005"),
        tax_source="external",
        aktieindkomst_threshold_dkk=Decimal("67500"),
    )


def _bridge_template(
    entity: str = "alice",
    liquid_account_id: str = "alice-ask",
    horizon_months: int = 120,
    bridge_start_year: int = 2055,
) -> BridgeTemplate:
    return BridgeTemplate(
        entity=entity,
        liquid_account_id=liquid_account_id,
        bridge_start_year=bridge_start_year,
        horizon_months=horizon_months,
        gross_annual_return_rate=Decimal("0.06"),
        annual_expense_ratio=Decimal("0.005"),
        account_type="ask",
        tax_regime="lager",
        aktieindkomst_threshold_dkk=Decimal("67500"),
    )


def _payout_template(
    entity: str = "alice",
    retirement_year: int = 2055,
    retirement_age: int = 65,
) -> PayoutTemplate:
    return PayoutTemplate(
        entity=entity,
        retirement_year=retirement_year,
        retirement_age=retirement_age,
        livrente_fraction=Decimal("0.70"),
        ratepension_fraction=Decimal("0.25"),
        ratepension_years=15,
        annuity_factor=Decimal("4800"),
        growth_rate_during_payout=Decimal("0.02"),
    )


def _folkepension_template(
    entity: str = "alice",
    civil_status: CivilStatus = "married",
) -> FolkepensionTemplate:
    return FolkepensionTemplate(entity=entity, civil_status=civil_status)


def _minimal_plan(
    horizon_years: int = 5,
    members: tuple[HouseholdMember, ...] | None = None,
) -> HouseholdPlan:
    """Minimal valid plan: one DK member, no liquid/bridge/payout sections."""
    if members is None:
        members = (_dk_member(),)
    return HouseholdPlan(
        base_year=BASE_YEAR,
        horizon_years=horizon_years,
        inflation_rate=Decimal("0.025"),
        eur_per_dkk=EUR_PER_DKK,
        members=members,
        salaries=(_salary("alice"),),
        contributions=(_contribution("alice"),),
        pension_rules=(_pension_rule("alice"),),
    )


def _full_plan() -> HouseholdPlan:
    """Full plan: DK member + DE member, liquid account, bridge, payout, folkepension."""
    dk = _dk_member(name="alice", retirement_year=2055, public_pension_start_year=2055 + 12)
    de = _de_member(name="bob", retirement_year=2050, public_pension_start_year=2050 + 15)
    tax_cfg = TaxConfig(regimes={"alice": DK_DEFAULT, "bob": DE_DEFAULT})
    spending = HouseholdSpendingPlan(
        rules=(
            SpendingRule(
                label="living",
                annual_amount=Decimal("40000"),
                currency="EUR",
                inflation_rate=Decimal("0.02"),
                inflation_base_year=BASE_YEAR,
            ),
        )
    )
    return HouseholdPlan(
        base_year=BASE_YEAR,
        horizon_years=35,
        inflation_rate=Decimal("0.025"),
        eur_per_dkk=EUR_PER_DKK,
        pension_market_return_rate=Decimal("0.07"),
        pal_skat_rate=Decimal("0.153"),
        members=(dk, de),
        salaries=(
            _salary("alice", gross_annual="75000"),
            _salary("bob", gross_annual="65000"),
        ),
        contributions=(_contribution("alice"),),
        pension_rules=(
            _pension_rule("alice"),
            _pension_rule("bob"),
        ),
        tax_config=tax_cfg,
        spending_plan=spending,
        liquid_configs=(_ask_account(),),
        bridge_templates=(_bridge_template(entity="alice"),),
        payout_templates=(_payout_template(entity="alice"),),
        folkepension_templates=(_folkepension_template(entity="alice"),),
    )


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestHouseholdMemberValidation:
    def test_public_pension_start_must_be_after_retirement(self) -> None:
        with pytest.raises(ValueError, match="public_pension_start_year"):
            HouseholdMember(
                name="x",
                birth_year=1980,
                jurisdiction="DK",
                retirement_year=2060,
                public_pension_start_year=2060,  # equal → invalid
            )

    def test_valid_with_none_public_pension(self) -> None:
        m = HouseholdMember(
            name="x",
            birth_year=1980,
            jurisdiction="DK",
            retirement_year=2060,
        )
        assert m.public_pension_start_year is None


class TestHouseholdPlanValidation:
    def test_empty_members_rejected(self) -> None:
        with pytest.raises(ValueError, match="members must not be empty"):
            HouseholdPlan(
                base_year=2024,
                horizon_years=10,
                inflation_rate=Decimal("0.02"),
                eur_per_dkk=Decimal("0.13"),
                members=(),
            )

    def test_horizon_zero_rejected(self) -> None:
        with pytest.raises(ValueError, match="horizon_years"):
            HouseholdPlan(
                base_year=2024,
                horizon_years=0,
                inflation_rate=Decimal("0.02"),
                eur_per_dkk=Decimal("0.13"),
                members=(_dk_member(),),
            )

    def test_payout_template_unknown_entity_rejected(self) -> None:
        with pytest.raises(ValueError, match="payout_templates entity 'ghost'"):
            HouseholdPlan(
                base_year=2024,
                horizon_years=10,
                inflation_rate=Decimal("0.02"),
                eur_per_dkk=Decimal("0.13"),
                members=(_dk_member(name="alice"),),
                payout_templates=(_payout_template(entity="ghost"),),
            )

    def test_folkepension_template_de_entity_rejected(self) -> None:
        with pytest.raises(ValueError, match="Folkepension only applies to DK"):
            HouseholdPlan(
                base_year=2024,
                horizon_years=10,
                inflation_rate=Decimal("0.02"),
                eur_per_dkk=Decimal("0.13"),
                members=(_de_member(name="bob"),),
                folkepension_templates=(_folkepension_template(entity="bob"),),
            )

    def test_duplicate_member_names_rejected(self) -> None:
        with pytest.raises(ValueError, match="Duplicate member names"):
            HouseholdPlan(
                base_year=2024,
                horizon_years=10,
                inflation_rate=Decimal("0.02"),
                eur_per_dkk=Decimal("0.13"),
                members=(_dk_member(name="alice"), _dk_member(name="alice")),
            )

    def test_duplicate_liquid_account_ids_rejected(self) -> None:
        dup_cfg = _ask_account(account_id="acc1")
        with pytest.raises(ValueError, match="Duplicate liquid_configs account_id"):
            HouseholdPlan(
                base_year=2024,
                horizon_years=10,
                inflation_rate=Decimal("0.02"),
                eur_per_dkk=Decimal("0.13"),
                members=(_dk_member(),),
                liquid_configs=(dup_cfg, dup_cfg),
            )

    def test_duplicate_bridge_entities_rejected(self) -> None:
        with pytest.raises(ValueError, match="Duplicate bridge_templates entities"):
            HouseholdPlan(
                base_year=2024,
                horizon_years=10,
                inflation_rate=Decimal("0.02"),
                eur_per_dkk=Decimal("0.13"),
                members=(_dk_member(name="alice"),),
                bridge_templates=(
                    _bridge_template(entity="alice"),
                    _bridge_template(entity="alice"),
                ),
            )

    def test_duplicate_payout_entities_rejected(self) -> None:
        with pytest.raises(ValueError, match="Duplicate payout_templates entities"):
            HouseholdPlan(
                base_year=2024,
                horizon_years=10,
                inflation_rate=Decimal("0.02"),
                eur_per_dkk=Decimal("0.13"),
                members=(_dk_member(name="alice"),),
                payout_templates=(
                    _payout_template(entity="alice"),
                    _payout_template(entity="alice"),
                ),
            )

    def test_folkepension_missing_public_pension_start_year_rejected(self) -> None:
        with pytest.raises(ValueError, match="public_pension_start_year"):
            HouseholdPlan(
                base_year=2024,
                horizon_years=10,
                inflation_rate=Decimal("0.02"),
                eur_per_dkk=Decimal("0.13"),
                members=(
                    _dk_member(name="alice", public_pension_start_year=None),
                ),
                folkepension_templates=(_folkepension_template(entity="alice"),),
            )

    def test_duplicate_folkepension_entities_rejected(self) -> None:
        with pytest.raises(ValueError, match="Duplicate folkepension_templates entities"):
            HouseholdPlan(
                base_year=2024,
                horizon_years=10,
                inflation_rate=Decimal("0.02"),
                eur_per_dkk=Decimal("0.13"),
                members=(_dk_member(name="alice"),),
                folkepension_templates=(
                    _folkepension_template(entity="alice"),
                    _folkepension_template(entity="alice"),
                ),
            )

    def test_duplicate_folkepension_entities_checked_before_jurisdiction(self) -> None:
        with pytest.raises(ValueError, match="Duplicate folkepension_templates entities"):
            HouseholdPlan(
                base_year=2024,
                horizon_years=10,
                inflation_rate=Decimal("0.02"),
                eur_per_dkk=Decimal("0.13"),
                members=(_de_member(name="bob"),),
                folkepension_templates=(
                    _folkepension_template(entity="bob"),
                    _folkepension_template(entity="bob"),
                ),
            )

    def test_bridge_lager_horizon_months_must_be_multiple_of_12(self) -> None:
        with pytest.raises(ValueError, match="horizon_months must be a multiple of 12"):
            _bridge_template(horizon_months=121)

    def test_bridge_liquid_account_id_must_reference_liquid_config(self) -> None:
        with pytest.raises(ValueError, match="liquid_account_id 'nonexistent'"):
            HouseholdPlan(
                base_year=2024,
                horizon_years=10,
                inflation_rate=Decimal("0.02"),
                eur_per_dkk=Decimal("0.13"),
                members=(_dk_member(name="alice"),),
                bridge_templates=(
                    _bridge_template(entity="alice", liquid_account_id="nonexistent"),
                ),
            )


# ---------------------------------------------------------------------------
# Phase helper tests
# ---------------------------------------------------------------------------


class TestHouseholdPhase:
    def _plan_with_timings(
        self,
        retirement_year: int,
        public_pension_start_year: int | None,
    ) -> HouseholdPlan:
        return _minimal_plan(
            horizon_years=30,
            members=(
                HouseholdMember(
                    name="alice",
                    birth_year=1980,
                    jurisdiction="DK",
                    retirement_year=retirement_year,
                    public_pension_start_year=public_pension_start_year,
                ),
            ),
        )

    def test_accumulation_during_employment(self) -> None:
        plan = self._plan_with_timings(2040, 2053)
        assert _household_phase(2030, plan) is SpendingPhase.ACCUMULATION

    def test_accumulation_at_retirement_year(self) -> None:
        plan = self._plan_with_timings(2040, 2053)
        assert _household_phase(2040, plan) is SpendingPhase.ACCUMULATION

    def test_bridge_one_year_after_retirement(self) -> None:
        plan = self._plan_with_timings(2040, 2053)
        assert _household_phase(2041, plan) is SpendingPhase.BRIDGE

    def test_retirement_at_public_pension_start(self) -> None:
        plan = self._plan_with_timings(2040, 2053)
        assert _household_phase(2053, plan) is SpendingPhase.RETIREMENT

    def test_bridge_forever_when_no_public_pension(self) -> None:
        plan = self._plan_with_timings(2040, None)
        assert _household_phase(2041, plan) is SpendingPhase.BRIDGE
        assert _household_phase(2080, plan) is SpendingPhase.BRIDGE


# ---------------------------------------------------------------------------
# Minimal plan projection
# ---------------------------------------------------------------------------


class TestMinimalPlan:
    def test_returns_result(self) -> None:
        plan = _minimal_plan(horizon_years=3)
        result = project_household(plan)
        assert isinstance(result, HouseholdProjectionResult)

    def test_no_warnings_on_clean_plan(self) -> None:
        plan = _minimal_plan(horizon_years=3)
        result = project_household(plan)
        assert result.warnings == ()

    def test_spending_years_length(self) -> None:
        plan = _minimal_plan(horizon_years=5)
        result = project_household(plan)
        assert len(result.spending_by_year) == 5

    def test_spending_years_are_consecutive(self) -> None:
        plan = _minimal_plan(horizon_years=5)
        result = project_household(plan)
        years = [sy.year for sy in result.spending_by_year]
        assert years == list(range(BASE_YEAR + 1, BASE_YEAR + 6))

    def test_no_liquid_bridge_payout_sections_are_empty(self) -> None:
        plan = _minimal_plan()
        result = project_household(plan)
        assert result.liquid_projections == ()
        assert result.bridge_results == ()
        assert result.payout_projections == ()
        assert result.folkepension_results == ()

    def test_cashflow_gross_has_flows(self) -> None:
        plan = _minimal_plan(horizon_years=3)
        result = project_household(plan)
        assert len(result.cashflow_gross.flows) > 0

    def test_cashflow_net_equals_gross_without_tax_config(self) -> None:
        plan = _minimal_plan(horizon_years=3)
        result = project_household(plan)
        # No tax_config means TaxConfig(regimes={}) — apply_tax is a no-op,
        # so net and gross salary totals are identical.
        gross_total = sum(f.gross_salary_eur for f in result.cashflow_gross.flows)
        net_total = sum(f.gross_salary_eur for f in result.cashflow_net.flows)
        assert net_total == gross_total


# ---------------------------------------------------------------------------
# Full plan projection (DK + DE household)
# ---------------------------------------------------------------------------


class TestFullPlan:
    @pytest.fixture(scope="class")
    def result(self) -> HouseholdProjectionResult:
        return project_household(_full_plan())

    def test_returns_result(self, result: HouseholdProjectionResult) -> None:
        assert isinstance(result, HouseholdProjectionResult)

    def test_liquid_projection_present(self, result: HouseholdProjectionResult) -> None:
        assert len(result.liquid_projections) == 1

    def test_bridge_result_present(self, result: HouseholdProjectionResult) -> None:
        assert len(result.bridge_results) == 1
        br = result.bridge_results[0]
        assert isinstance(br, EntityBridgeResult)
        assert br.entity == "alice"

    def test_payout_projection_present(self, result: HouseholdProjectionResult) -> None:
        assert len(result.payout_projections) == 1
        pp = result.payout_projections[0]
        assert pp.config.entity == "alice"

    def test_folkepension_result_present(self, result: HouseholdProjectionResult) -> None:
        assert len(result.folkepension_results) == 1
        fp = result.folkepension_results[0]
        assert isinstance(fp, EntityFolkepensionResult)
        assert fp.entity == "alice"
        assert fp.result.total_monthly_dkk > Decimal("0")

    def test_spending_all_phases_represented(
        self, result: HouseholdProjectionResult
    ) -> None:
        phases = {sy.phase for sy in result.spending_by_year}
        assert SpendingPhase.ACCUMULATION in phases

    def test_spending_totals_non_negative(
        self, result: HouseholdProjectionResult
    ) -> None:
        for sy in result.spending_by_year:
            assert isinstance(sy, SpendingYear)
            assert sy.total_eur >= Decimal("0")
            assert sy.total_dkk >= Decimal("0")

    def test_audit_record_populated(self, result: HouseholdProjectionResult) -> None:
        assert len(result.audit_record.assumptions) > 0

    def test_payout_balance_derived_from_cashflow(
        self, result: HouseholdProjectionResult
    ) -> None:
        # The payout pension_balance_eur must equal the cashflow net balance
        # at the entity's retirement year.
        payout = result.payout_projections[0]
        retirement_year = 2055
        matching = [
            f
            for f in result.cashflow_net.flows
            if f.year == retirement_year and f.entity == "alice"
        ]
        assert matching, "No cashflow flow for alice at retirement year"
        expected_balance = matching[0].cumulative_pension_eur
        assert payout.config.pension_balance_eur == expected_balance


# ---------------------------------------------------------------------------
# Warning emission
# ---------------------------------------------------------------------------


class TestWarnings:
    def test_bridge_start_year_outside_projection_emits_warning(self) -> None:
        plan = HouseholdPlan(
            base_year=BASE_YEAR,
            horizon_years=5,
            inflation_rate=Decimal("0.025"),
            eur_per_dkk=EUR_PER_DKK,
            members=(_dk_member(),),
            liquid_configs=(_ask_account(),),
            bridge_templates=(
                _bridge_template(entity="alice", bridge_start_year=BASE_YEAR + 50),
            ),
        )
        result = project_household(plan)
        assert len(result.warnings) == 1
        w = result.warnings[0]
        assert isinstance(w, ProjectionWarning)
        assert w.code == "bridge_start_year_not_in_projection"
        assert w.entity == "alice"
        assert str(BASE_YEAR + 50) in w.message
        assert result.bridge_results == ()

    def test_missing_cashflow_entity_for_payout_emits_warning(self) -> None:
        # A payout template for an entity with no salary/pension rules →
        # retirement_year lookup fails because entity never appears in flows.
        plan = HouseholdPlan(
            base_year=BASE_YEAR,
            horizon_years=5,
            inflation_rate=Decimal("0.025"),
            eur_per_dkk=EUR_PER_DKK,
            members=(_dk_member(name="alice"),),
            # No salaries/pension_rules for alice → no flows → KeyError in payout_at
            payout_templates=(
                PayoutTemplate(
                    entity="alice",
                    retirement_year=BASE_YEAR + 1,
                    retirement_age=65,
                    livrente_fraction=Decimal("0.70"),
                    ratepension_fraction=Decimal("0.25"),
                    ratepension_years=15,
                    annuity_factor=Decimal("4800"),
                ),
            ),
        )
        result = project_household(plan)
        assert len(result.warnings) == 1
        w = result.warnings[0]
        assert w.code == "payout_entity_cashflow_not_found"
        assert result.payout_projections == ()

    def test_unsupported_folkepension_age_emits_warning(self) -> None:
        plan = HouseholdPlan(
            base_year=BASE_YEAR,
            horizon_years=5,
            inflation_rate=Decimal("0.025"),
            eur_per_dkk=EUR_PER_DKK,
            members=(
                _dk_member(
                    retirement_year=2020,
                    public_pension_start_year=2025,
                ),
            ),
            salaries=(_salary("alice"),),
            folkepension_templates=(_folkepension_template(entity="alice"),),
        )
        result = project_household(plan)
        assert len(result.warnings) == 1
        w = result.warnings[0]
        assert w.code == "folkepension_age_unsupported"
        assert w.entity == "alice"
        assert "2025" in w.message
        assert result.folkepension_results == ()
