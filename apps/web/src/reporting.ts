export type Currency = "DKK" | "EUR";

export type MetricTone = "good" | "watch" | "critical" | "info";

export type DashboardMetric = {
  readonly id: string;
  readonly label: string;
  readonly value: number;
  readonly unit: Currency | "months" | "percent" | "year";
  readonly deltaLabel: string;
  readonly tone: MetricTone;
  readonly evidence: string;
};

export type TimelinePoint = {
  readonly year: number;
  readonly netWorthDkk: number;
  readonly liquidDkk: number;
  readonly pensionDkk: number;
};

export type Risk = {
  readonly code: string;
  readonly severity: "info" | "warning" | "critical";
  readonly title: string;
  readonly nextAction: string;
};

export type PlanningQuestion = {
  readonly id:
    | "can_we_retire"
    | "what_breaks_first"
    | "how_do_taxes_affect_plan"
    | "which_assumptions_matter"
    | "which_scenarios_should_we_test";
  readonly question: string;
  readonly status: "ready" | "watch" | "info";
  readonly summary: string;
  readonly evidenceCount: number;
};

export type DashboardData = {
  readonly generatedAt: string;
  readonly householdLabel: string;
  readonly metrics: readonly DashboardMetric[];
  readonly timeline: readonly TimelinePoint[];
  readonly risks: readonly Risk[];
  readonly planningQuestions: readonly PlanningQuestion[];
};

export const demoDashboard: DashboardData = {
  generatedAt: "2026-05-17T18:00:00.000Z",
  householdLabel: "Synthetic DK/DE household",
  metrics: [
    {
      id: "net-worth",
      label: "Net worth",
      value: 8_740_000,
      unit: "DKK",
      deltaLabel: "+4.8% year to date",
      tone: "good",
      evidence: "analytics_marts.mart_net_worth_daily",
    },
    {
      id: "liquidity-runway",
      label: "Liquidity runway",
      value: 54,
      unit: "months",
      deltaLabel: "Bridge phase funded",
      tone: "good",
      evidence: "penge.sim.balance_sheet",
    },
    {
      id: "fire-readiness",
      label: "FIRE readiness",
      value: 82,
      unit: "percent",
      deltaLabel: "Watch tax drag",
      tone: "watch",
      evidence: "penge.sim.readiness",
    },
    {
      id: "retire-year",
      label: "Median FI year",
      value: 2034,
      unit: "year",
      deltaLabel: "Synthetic scenario pack",
      tone: "info",
      evidence: "penge.sim.household_scenarios",
    },
  ],
  timeline: [
    { year: 2026, netWorthDkk: 8_740_000, liquidDkk: 1_450_000, pensionDkk: 4_300_000 },
    { year: 2027, netWorthDkk: 9_180_000, liquidDkk: 1_610_000, pensionDkk: 4_610_000 },
    { year: 2028, netWorthDkk: 9_710_000, liquidDkk: 1_760_000, pensionDkk: 4_980_000 },
    { year: 2029, netWorthDkk: 10_260_000, liquidDkk: 1_880_000, pensionDkk: 5_360_000 },
    { year: 2030, netWorthDkk: 10_880_000, liquidDkk: 2_020_000, pensionDkk: 5_790_000 },
    { year: 2031, netWorthDkk: 11_470_000, liquidDkk: 2_180_000, pensionDkk: 6_210_000 },
  ],
  risks: [
    {
      code: "dk-lager-tax-drag",
      severity: "warning",
      title: "DK lager taxation lowers spendable liquidity in weak years.",
      nextAction: "Compare ASK/frie midler routing before changing contributions.",
    },
    {
      code: "de-vorabpauschale-review",
      severity: "info",
      title: "DE Vorabpauschale assumptions need yearly source review.",
      nextAction: "Refresh basiszins and Teilfreistellung assumptions before tax close.",
    },
  ],
  planningQuestions: [
    {
      id: "can_we_retire",
      question: "Can we retire on the planned timeline?",
      status: "ready",
      summary: "Baseline is ready if the liquidity bridge remains ring-fenced.",
      evidenceCount: 4,
    },
    {
      id: "what_breaks_first",
      question: "What breaks first if the plan fails?",
      status: "watch",
      summary: "First weak point is liquid bridge depletion under lower-return stress.",
      evidenceCount: 5,
    },
    {
      id: "how_do_taxes_affect_plan",
      question: "How do DK/DE taxes affect this plan?",
      status: "watch",
      summary: "Tax drag is visible in both ASK/frie midler routing and DE fund taxation.",
      evidenceCount: 6,
    },
  ],
};

export function formatMetricValue(metric: DashboardMetric): string {
  const roundedValue = Math.round(metric.value);
  switch (metric.unit) {
    case "DKK":
    case "EUR":
      return `${new Intl.NumberFormat("en-DK").format(roundedValue)} ${metric.unit}`;
    case "months":
      return `${roundedValue} months`;
    case "percent":
      return `${roundedValue}%`;
    case "year":
      return `${roundedValue}`;
  }
}

export function liquidityShare(point: TimelinePoint): number {
  if (point.netWorthDkk <= 0) {
    return 0;
  }
  return point.liquidDkk / point.netWorthDkk;
}

export function riskCountBySeverity(risks: readonly Risk[], severity: Risk["severity"]): number {
  return risks.filter((risk) => risk.severity === severity).length;
}

export function buildMcpQuestionPayload(questions: readonly PlanningQuestion[]): {
  readonly plan_id: "synthetic_household";
  readonly questions: readonly PlanningQuestion["id"][];
} {
  return {
    plan_id: "synthetic_household",
    questions: questions.map((question) => question.id),
  };
}
