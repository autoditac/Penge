"""Tests for DK/DE household tax-context reporting."""

from __future__ import annotations

from penge.sim.household_tax_context import build_household_tax_context
from penge.sim.plan import HouseholdMember, project_household
from penge.sim.readiness import generate_readiness_report
from penge.sim.risk import generate_risk_register
from penge.sim.tax import DE_DEFAULT, DK_DEFAULT, TaxConfig
from tests.sim.planning_output_helpers import household_output_plan


def test_tax_context_distinguishes_dk_and_de_members_and_flags_de_limits() -> None:
    base = household_output_plan()
    plan = base.model_copy(
        update={
            "members": (
                *base.members,
                HouseholdMember(
                    name="bob",
                    birth_year=1982,
                    jurisdiction="DE",
                    tax_country="DE",
                    retirement_year=2029,
                    public_pension_start_year=2038,
                ),
            ),
            "tax_config": TaxConfig(regimes={"alice": DK_DEFAULT, "bob": DE_DEFAULT}),
        }
    )

    context = build_household_tax_context(plan)
    result = project_household(plan)
    report = generate_readiness_report(result)
    risk_register = generate_risk_register(result)

    member_contexts = {member.member: member for member in context.members}
    assert member_contexts["alice"].tax_country == "DK"
    assert member_contexts["bob"].tax_country == "DE"
    assert (
        member_contexts["bob"].capital_gains_effective_rate
        == DE_DEFAULT.capital_gains_effective_rate
    )
    assert {feature.code for feature in context.unsupported_features} >= {
        "de_vorabpauschale_not_in_household_plan",
        "de_income_tax_brackets_not_modelled",
    }
    assert "## Tax-country assumptions" in report.markdown
    assert "de_vorabpauschale_not_in_household_plan" in report.markdown
    assert "de_income_tax_brackets_not_modelled" in {
        finding.code for finding in risk_register.findings
    }
