import type { AnswerPlanningQuestionOutput } from "../../src/tools/answerPlanningQuestion.js";

export const PLANNING_SURFACE_PAYLOAD: AnswerPlanningQuestionOutput = {
  plan_id: "synthetic_household",
  surface: "household_planning_questions",
  generated_by: "penge.sim.planning_surface",
  overall_status: "watch",
  questions: [
    {
      question_id: "can_we_retire",
      question: "Can this household retire on the planned timeline?",
      status: "watch",
      answer:
        "The plan is watch for retirement in 2029. Terminal spendable liquidity is 500,000.00 DKK and terminal net worth is 10,500,000.00 DKK. Review the linked risks before treating this as a decision.",
      evidence: [
        { label: "planned_retirement_year", value: "2029", source: "RetirementReadinessReport" },
        {
          label: "terminal_spendable_liquidity_dkk",
          value: "500,000.00 DKK",
          source: "HouseholdBalanceSheet",
        },
      ],
      risk_codes: ["de_vorabpauschale_not_in_household_plan"],
      assumption_keys: ["planned_retirement_year", "annual_spending_plan", "eur_per_dkk"],
      limitation_codes: ["planning_grade_not_filing_advice"],
      docs: ["docs/sim/planning-outputs.md"],
    },
    {
      question_id: "what_breaks_first",
      question: "What breaks first if the plan fails?",
      status: "watch",
      answer:
        "The first material issue is `de_vorabpauschale_not_in_household_plan` in unknown year: DE depot planning uses an effective capital-gains rate.",
      evidence: [
        {
          label: "risk_code",
          value: "de_vorabpauschale_not_in_household_plan",
          source: "PlanningRiskRegister",
        },
      ],
      risk_codes: ["de_vorabpauschale_not_in_household_plan"],
      assumption_keys: ["tax_config"],
      limitation_codes: ["planning_grade_not_filing_advice"],
      docs: ["docs/sim/planning-outputs.md"],
    },
    {
      question_id: "how_do_taxes_affect_plan",
      question: "How do taxes affect this plan?",
      status: "watch",
      answer:
        "The planning report estimates 10,000.00 DKK liquid-depot tax, 5,000.00 DKK bridge tax, and 50,000.00 DKK total timeline tax drag. DK/DE limitations are surfaced as linked risks where relevant.",
      evidence: [
        {
          label: "total_timeline_tax_drag_dkk",
          value: "50,000.00 DKK",
          source: "TaxTimeline",
        },
      ],
      risk_codes: ["de_vorabpauschale_not_in_household_plan"],
      assumption_keys: ["tax_config", "household_tax_context", "DK_DEFAULT", "DE_DEFAULT"],
      limitation_codes: ["planning_grade_not_filing_advice"],
      docs: ["docs/tax/dk.md", "docs/tax/de.md"],
    },
  ],
  risks: [
    {
      code: "de_vorabpauschale_not_in_household_plan",
      severity: "warning",
      message: "DE depot planning uses an effective capital-gains rate.",
      affected_year: null,
      source_assumption: "TaxConfig",
      next_action: "Review German depot tax assumptions before deciding.",
    },
  ],
  assumptions: [
    {
      key: "planned_retirement_year",
      value: "2029",
      unit: "year",
      source: "HouseholdPlan.members",
      notes: "",
    },
    {
      key: "annual_spending_plan",
      value: "300,000.00 DKK",
      unit: "DKK/year",
      source: "HouseholdSpendingPlan",
      notes: "",
    },
    {
      key: "eur_per_dkk",
      value: "0.134",
      unit: "EUR per DKK",
      source: "ECB FX assumption",
      notes: "",
    },
    {
      key: "tax_config",
      value: "alice,bob",
      unit: "entity regimes",
      source: "TaxConfig",
      notes: "",
    },
    {
      key: "household_tax_context",
      value: "alice:DK, bob:DE",
      unit: "tax country",
      source: "HouseholdMember.tax_country",
      notes: "",
    },
  ],
  limitations: [
    {
      code: "planning_grade_not_filing_advice",
      message:
        "Household planning outputs are decision-support estimates, not filing-grade tax calculations or investment advice.",
      docs: ["docs/sim/planning-outputs.md", "docs/tax/dk.md", "docs/tax/de.md"],
    },
  ],
  docs: [
    "docs/sim/personas.md",
    "docs/sim/planning-outputs.md",
    "docs/tax/dk.md",
    "docs/tax/de.md",
  ],
};
