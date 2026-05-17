import { describe, expect, it } from "vitest";

import {
  buildMcpQuestionPayload,
  demoDashboard,
  formatMetricValue,
  liquidityShare,
  riskCountBySeverity,
} from "../src/reporting";

describe("reporting helpers", () => {
  it("formats dashboard metrics with explicit units", () => {
    const [netWorth, runway, readiness] = demoDashboard.metrics;
    if (netWorth === undefined || runway === undefined || readiness === undefined) {
      throw new Error("demo dashboard metrics fixture is incomplete");
    }

    expect(formatMetricValue(netWorth)).toContain("DKK");
    expect(formatMetricValue(runway)).toBe("54 months");
    expect(formatMetricValue(readiness)).toBe("82%");
  });

  it("computes liquidity share from deterministic reporting rows", () => {
    const [firstPoint] = demoDashboard.timeline;
    if (firstPoint === undefined) {
      throw new Error("demo dashboard timeline fixture is incomplete");
    }

    expect(liquidityShare(firstPoint)).toBeCloseTo(0.166, 3);
    expect(liquidityShare({ year: 2032, netWorthDkk: 0, liquidDkk: 10, pensionDkk: 0 })).toBe(0);
  });

  it("counts review risks by severity", () => {
    expect(riskCountBySeverity(demoDashboard.risks, "warning")).toBe(1);
    expect(riskCountBySeverity(demoDashboard.risks, "critical")).toBe(0);
  });

  it("builds the MCP payload without exposing raw household data", () => {
    expect(buildMcpQuestionPayload(demoDashboard.planningQuestions)).toEqual({
      plan_id: "synthetic_household",
      questions: ["can_we_retire", "what_breaks_first", "how_do_taxes_affect_plan"],
    });
  });
});
