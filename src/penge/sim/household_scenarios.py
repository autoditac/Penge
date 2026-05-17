"""Household-level scenario presets for FIRE planning workflows."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal

import pydantic

from penge.sim.cashflow import ContributionRule, PensionAccrualRule, SalaryRule
from penge.sim.liquid import LiquidDepotConfig
from penge.sim.plan import (
    HouseholdMember,
    HouseholdPlan,
)
from penge.sim.spending import OneOffExpense, SpendingRule

__all__ = [
    "DelayedPensionStartPreset",
    "HigherInflationPreset",
    "HigherSpendingPreset",
    "HouseholdScenario",
    "HouseholdScenarioPreset",
    "HouseholdScenarioPresetName",
    "IncreasedSavingsPreset",
    "LowerReturnsPreset",
    "LowerSavingsPreset",
    "OneOffExpensePreset",
    "RetireInYearPreset",
    "WorkReductionPreset",
    "apply_scenario_preset",
    "compose_scenario_presets",
]

_TWO_DP = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)


HouseholdScenarioPresetName = Literal[
    "retire_in_year",
    "work_reduction",
    "increased_savings",
    "lower_savings",
    "lower_returns",
    "higher_inflation",
    "higher_spending",
    "one_off_expense",
    "delayed_pension_start",
]


class HouseholdScenario(pydantic.BaseModel):
    """A labelled household scenario derived from a baseline plan."""

    model_config = pydantic.ConfigDict(frozen=True)

    name: str
    label: str
    description: str
    plan: HouseholdPlan
    changed_assumptions: tuple[str, ...]


class _PresetBase(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    name: HouseholdScenarioPresetName
    label: str
    description: str

    def apply(self, plan: HouseholdPlan) -> HouseholdScenario:
        raise NotImplementedError

    def _scenario(self, plan: HouseholdPlan, changes: tuple[str, ...]) -> HouseholdScenario:
        return HouseholdScenario(
            name=self.name,
            label=self.label,
            description=self.description,
            plan=plan,
            changed_assumptions=changes,
        )


class RetireInYearPreset(_PresetBase):
    """Set all household retirement and bridge/payout start years to one year."""

    name: Literal["retire_in_year"] = "retire_in_year"
    label: str = "Retire in target year"
    description: str = "Move household retirement, bridge, and payout start to a target year."
    year: int

    def apply(self, plan: HouseholdPlan) -> HouseholdScenario:
        for member in plan.members:
            if (
                member.public_pension_start_year is not None
                and member.public_pension_start_year < self.year
            ):
                raise ValueError(
                    "retire_in_year must not be after any configured public pension start"
                )
        members = tuple(
            member.model_copy(update={"retirement_year": self.year}) for member in plan.members
        )
        bridge_templates = tuple(
            template.model_copy(update={"bridge_start_year": self.year})
            for template in plan.bridge_templates
        )
        payout_templates = tuple(
            template.model_copy(update={"retirement_year": self.year})
            for template in plan.payout_templates
        )
        scenario_plan = plan.model_copy(
            update={
                "members": members,
                "bridge_templates": bridge_templates,
                "payout_templates": payout_templates,
            }
        )
        return self._scenario(scenario_plan, (f"retirement_year -> {self.year}",))


class WorkReductionPreset(_PresetBase):
    """Reduce one member's salary and salary-linked pension accrual from a year."""

    name: Literal["work_reduction"] = "work_reduction"
    label: str = "One spouse reduces work"
    description: str = "Scale salary and defined-contribution pension accrual from a start year."
    entity: str
    start_year: int
    fte_fraction: Decimal

    @pydantic.field_validator("fte_fraction", mode="before")
    @classmethod
    def _coerce_fraction(cls, value: object) -> Decimal:
        return Decimal(str(value))

    @pydantic.model_validator(mode="after")
    def _validate(self) -> WorkReductionPreset:
        if not (Decimal("0") < self.fte_fraction <= Decimal("1")):
            raise ValueError("fte_fraction must be in (0, 1]")
        return self

    def apply(self, plan: HouseholdPlan) -> HouseholdScenario:
        salaries = tuple(
            item for rule in plan.salaries for item in _work_reduced_salary_rules(rule, self)
        )
        pension_rules = tuple(
            item for rule in plan.pension_rules for item in _work_reduced_pension_rules(rule, self)
        )
        scenario_plan = plan.model_copy(
            update={"salaries": salaries, "pension_rules": pension_rules}
        )
        return self._scenario(
            scenario_plan,
            (f"{self.entity} salary/accrual x {self.fte_fraction} from {self.start_year}",),
        )


class IncreasedSavingsPreset(_PresetBase):
    """Increase liquid savings budgets in cashflow and liquid account configs."""

    name: Literal["increased_savings"] = "increased_savings"
    label: str = "Increased monthly savings"
    description: str = "Increase liquid contribution budgets by a monthly DKK amount."
    monthly_delta_dkk: Decimal
    entity: str | None = None
    account_id: str | None = None

    @pydantic.field_validator("monthly_delta_dkk", mode="before")
    @classmethod
    def _coerce_delta(cls, value: object) -> Decimal:
        return Decimal(str(value))

    @pydantic.model_validator(mode="after")
    def _validate(self) -> IncreasedSavingsPreset:
        if self.monthly_delta_dkk <= Decimal("0"):
            raise ValueError("monthly_delta_dkk must be > 0")
        return self

    def apply(self, plan: HouseholdPlan) -> HouseholdScenario:
        annual_delta_dkk = _q(self.monthly_delta_dkk * Decimal("12"))
        matching_contribution_count = sum(
            1 for rule in plan.contributions if _contribution_rule_matches(rule, self)
        )
        matching_liquid_config_count = sum(
            1 for config in plan.liquid_configs if _liquid_config_matches(config, self)
        )
        contributions = tuple(
            _increase_contribution_rule(
                rule,
                self,
                annual_delta_dkk,
                plan.eur_per_dkk,
                matching_contribution_count,
            )
            for rule in plan.contributions
        )
        liquid_configs = tuple(
            _increase_liquid_config(config, self, annual_delta_dkk, matching_liquid_config_count)
            for config in plan.liquid_configs
        )
        scenario_plan = plan.model_copy(
            update={"contributions": contributions, "liquid_configs": liquid_configs}
        )
        return self._scenario(
            scenario_plan,
            (f"monthly liquid savings +{self.monthly_delta_dkk} DKK",),
        )


class LowerSavingsPreset(_PresetBase):
    """Scale liquid savings budgets down by a factor."""

    name: Literal["lower_savings"] = "lower_savings"
    label: str = "Lower savings"
    description: str = "Reduce liquid contribution budgets by a deterministic factor."
    factor: Decimal = Decimal("0.75")

    @pydantic.field_validator("factor", mode="before")
    @classmethod
    def _coerce_factor(cls, value: object) -> Decimal:
        return Decimal(str(value))

    @pydantic.model_validator(mode="after")
    def _validate(self) -> LowerSavingsPreset:
        if not (Decimal("0") < self.factor <= Decimal("1")):
            raise ValueError("factor must be in (0, 1]")
        return self

    def apply(self, plan: HouseholdPlan) -> HouseholdScenario:
        contributions = tuple(
            rule.model_copy(update={"annual": _q(rule.annual * self.factor)})
            for rule in plan.contributions
        )
        liquid_configs = tuple(
            config.model_copy(
                update={"annual_contribution_dkk": _q(config.annual_contribution_dkk * self.factor)}
            )
            for config in plan.liquid_configs
        )
        scenario_plan = plan.model_copy(
            update={"contributions": contributions, "liquid_configs": liquid_configs}
        )
        return self._scenario(scenario_plan, (f"liquid savings x {self.factor}",))


class LowerReturnsPreset(_PresetBase):
    """Lower pension, liquid, and bridge return assumptions by a fixed delta."""

    name: Literal["lower_returns"] = "lower_returns"
    label: str = "Lower returns"
    description: str = "Reduce projected investment-return assumptions."
    annual_return_delta: Decimal = Decimal("-0.02")

    @pydantic.field_validator("annual_return_delta", mode="before")
    @classmethod
    def _coerce_delta(cls, value: object) -> Decimal:
        return Decimal(str(value))

    def apply(self, plan: HouseholdPlan) -> HouseholdScenario:
        liquid_configs = tuple(
            config.model_copy(
                update={
                    "gross_annual_return_rate": config.gross_annual_return_rate
                    + self.annual_return_delta
                }
            )
            for config in plan.liquid_configs
        )
        bridge_templates = tuple(
            template.model_copy(
                update={
                    "gross_annual_return_rate": template.gross_annual_return_rate
                    + self.annual_return_delta
                }
            )
            for template in plan.bridge_templates
        )
        scenario_plan = plan.model_copy(
            update={
                "pension_market_return_rate": plan.pension_market_return_rate
                + self.annual_return_delta,
                "liquid_configs": liquid_configs,
                "bridge_templates": bridge_templates,
            }
        )
        return self._scenario(
            scenario_plan,
            (f"investment returns {self.annual_return_delta:+} annual",),
        )


class HigherInflationPreset(_PresetBase):
    """Raise household inflation assumptions."""

    name: Literal["higher_inflation"] = "higher_inflation"
    label: str = "Higher inflation"
    description: str = "Set plan and spending-rule inflation assumptions to a higher rate."
    inflation_rate: Decimal
    update_spending_rules: bool = True

    @pydantic.field_validator("inflation_rate", mode="before")
    @classmethod
    def _coerce_rate(cls, value: object) -> Decimal:
        return Decimal(str(value))

    def apply(self, plan: HouseholdPlan) -> HouseholdScenario:
        spending_plan = plan.spending_plan
        if self.update_spending_rules:
            spending_plan = spending_plan.model_copy(
                update={
                    "rules": tuple(
                        rule.model_copy(update={"inflation_rate": self.inflation_rate})
                        for rule in spending_plan.rules
                    )
                }
            )
        scenario_plan = plan.model_copy(
            update={
                "inflation_rate": self.inflation_rate,
                "spending_plan": spending_plan,
            }
        )
        return self._scenario(scenario_plan, (f"inflation_rate -> {self.inflation_rate}",))


class HigherSpendingPreset(_PresetBase):
    """Scale recurring and one-off spending by a factor."""

    name: Literal["higher_spending"] = "higher_spending"
    label: str = "Higher spending"
    description: str = "Scale household spending assumptions by a deterministic factor."
    factor: Decimal

    @pydantic.field_validator("factor", mode="before")
    @classmethod
    def _coerce_factor(cls, value: object) -> Decimal:
        return Decimal(str(value))

    @pydantic.model_validator(mode="after")
    def _validate(self) -> HigherSpendingPreset:
        if self.factor <= Decimal("0"):
            raise ValueError("factor must be > 0")
        return self

    def apply(self, plan: HouseholdPlan) -> HouseholdScenario:
        spending_plan = plan.spending_plan.model_copy(
            update={
                "rules": tuple(
                    _scale_spending_rule(rule, self.factor) for rule in plan.spending_plan.rules
                ),
                "one_offs": tuple(
                    one_off.model_copy(update={"amount": _q(one_off.amount * self.factor)})
                    for one_off in plan.spending_plan.one_offs
                ),
            }
        )
        scenario_plan = plan.model_copy(update={"spending_plan": spending_plan})
        return self._scenario(scenario_plan, (f"spending x {self.factor}",))


class OneOffExpensePreset(_PresetBase):
    """Add a one-off household expense."""

    name: Literal["one_off_expense"] = "one_off_expense"
    label: str = "One-off large expense"
    description: str = "Add a single large expense to the household spending plan."
    year: int
    amount: Decimal
    currency: Literal["EUR", "DKK"] = "DKK"
    expense_label: str = "scenario one-off expense"

    @pydantic.field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, value: object) -> Decimal:
        return Decimal(str(value))

    def apply(self, plan: HouseholdPlan) -> HouseholdScenario:
        one_off = OneOffExpense(
            label=self.expense_label,
            year=self.year,
            amount=self.amount,
            currency=self.currency,
        )
        spending_plan = plan.spending_plan.model_copy(
            update={"one_offs": (*plan.spending_plan.one_offs, one_off)}
        )
        scenario_plan = plan.model_copy(update={"spending_plan": spending_plan})
        return self._scenario(
            scenario_plan,
            (f"one-off {self.amount} {self.currency} in {self.year}",),
        )


class DelayedPensionStartPreset(_PresetBase):
    """Delay public pension start years by a fixed number of years."""

    name: Literal["delayed_pension_start"] = "delayed_pension_start"
    label: str = "Delayed pension start"
    description: str = "Delay public pension access assumptions by a fixed number of years."
    delay_years: int

    @pydantic.model_validator(mode="after")
    def _validate(self) -> DelayedPensionStartPreset:
        if self.delay_years < 1:
            raise ValueError("delay_years must be >= 1")
        return self

    def apply(self, plan: HouseholdPlan) -> HouseholdScenario:
        members = tuple(
            _delay_member_public_pension(member, self.delay_years) for member in plan.members
        )
        scenario_plan = plan.model_copy(update={"members": members})
        return self._scenario(
            scenario_plan,
            (f"public pension start +{self.delay_years} years",),
        )


HouseholdScenarioPreset = (
    RetireInYearPreset
    | WorkReductionPreset
    | IncreasedSavingsPreset
    | LowerSavingsPreset
    | LowerReturnsPreset
    | HigherInflationPreset
    | HigherSpendingPreset
    | OneOffExpensePreset
    | DelayedPensionStartPreset
)


def apply_scenario_preset(
    plan: HouseholdPlan,
    preset: HouseholdScenarioPreset,
) -> HouseholdScenario:
    """Apply one typed scenario preset to a household plan."""

    return preset.apply(plan)


def compose_scenario_presets(
    plan: HouseholdPlan,
    presets: tuple[HouseholdScenarioPreset, ...],
    *,
    name: str = "composed",
    label: str = "Composed scenario",
    description: str = "Composition of multiple household scenario presets.",
) -> HouseholdScenario:
    """Apply several safe scenario presets in order and return one labelled scenario."""

    current_plan = plan
    changes: list[str] = []
    for preset in presets:
        scenario = preset.apply(current_plan)
        current_plan = scenario.plan
        changes.extend(f"{preset.name}: {change}" for change in scenario.changed_assumptions)
    return HouseholdScenario(
        name=name,
        label=label,
        description=description,
        plan=current_plan,
        changed_assumptions=tuple(changes),
    )


def _work_reduced_salary_rules(
    rule: SalaryRule,
    preset: WorkReductionPreset,
) -> tuple[SalaryRule, ...]:
    if rule.entity != preset.entity:
        return (rule,)
    if rule.active_until is not None and rule.active_until < preset.start_year:
        return (rule,)
    reduced = rule.model_copy(
        update={
            "gross_annual": _q(rule.gross_annual * preset.fte_fraction),
            "active_from": (
                preset.start_year
                if rule.active_from is None
                else max(rule.active_from, preset.start_year)
            ),
        }
    )
    if rule.active_from is not None and rule.active_from >= preset.start_year:
        return (reduced,)
    return (rule.model_copy(update={"active_until": preset.start_year - 1}), reduced)


def _work_reduced_pension_rules(
    rule: PensionAccrualRule,
    preset: WorkReductionPreset,
) -> tuple[PensionAccrualRule, ...]:
    if rule.entity != preset.entity or rule.kind != "dc_fraction":
        return (rule,)
    if rule.active_until is not None and rule.active_until < preset.start_year:
        return (rule,)
    if rule.dc_fraction is None:
        return (rule,)
    reduced = rule.model_copy(
        update={
            "dc_fraction": _q(rule.dc_fraction * preset.fte_fraction),
            "active_from": (
                preset.start_year
                if rule.active_from is None
                else max(rule.active_from, preset.start_year)
            ),
        }
    )
    if rule.active_from is not None and rule.active_from >= preset.start_year:
        return (reduced,)
    return (rule.model_copy(update={"active_until": preset.start_year - 1}), reduced)


def _increase_contribution_rule(
    rule: ContributionRule,
    preset: IncreasedSavingsPreset,
    annual_delta_dkk: Decimal,
    eur_per_dkk: Decimal,
    matching_count: int,
) -> ContributionRule:
    if matching_count == 0 or not _contribution_rule_matches(rule, preset):
        return rule
    per_rule_annual_delta_dkk = annual_delta_dkk / Decimal(matching_count)
    if rule.currency == "DKK":
        annual = _q(rule.annual + per_rule_annual_delta_dkk)
    else:
        annual = _q(rule.annual + per_rule_annual_delta_dkk * eur_per_dkk)
    return rule.model_copy(update={"annual": annual})


def _increase_liquid_config(
    config: LiquidDepotConfig,
    preset: IncreasedSavingsPreset,
    annual_delta_dkk: Decimal,
    matching_count: int,
) -> LiquidDepotConfig:
    if matching_count == 0 or not _liquid_config_matches(config, preset):
        return config
    per_config_annual_delta_dkk = annual_delta_dkk / Decimal(matching_count)
    return config.model_copy(
        update={
            "annual_contribution_dkk": _q(
                config.annual_contribution_dkk + per_config_annual_delta_dkk
            )
        }
    )


def _contribution_rule_matches(
    rule: ContributionRule,
    preset: IncreasedSavingsPreset,
) -> bool:
    return preset.entity is None or rule.entity == preset.entity


def _liquid_config_matches(
    config: LiquidDepotConfig,
    preset: IncreasedSavingsPreset,
) -> bool:
    return preset.account_id is None or config.account_id == preset.account_id


def _scale_spending_rule(rule: SpendingRule, factor: Decimal) -> SpendingRule:
    return rule.model_copy(update={"annual_amount": _q(rule.annual_amount * factor)})


def _delay_member_public_pension(member: HouseholdMember, delay_years: int) -> HouseholdMember:
    if member.public_pension_start_year is None:
        return member
    return member.model_copy(
        update={"public_pension_start_year": member.public_pension_start_year + delay_years}
    )
