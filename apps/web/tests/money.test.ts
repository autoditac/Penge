import { describe, expect, it } from "vitest";

import {
  formatCompact,
  formatMoney,
  formatShare,
  isoDate,
  isoDaysAgo,
  parseDecimal,
} from "../src/money";

describe("parseDecimal", () => {
  it("parses decimal wire strings", () => {
    expect(parseDecimal("1234.5600")).toBeCloseTo(1234.56);
    expect(parseDecimal("-0.25")).toBeCloseTo(-0.25);
    expect(parseDecimal("0")).toBe(0);
  });

  it("returns null for null input", () => {
    expect(parseDecimal(null)).toBeNull();
  });

  it("returns null for non-numeric strings", () => {
    expect(parseDecimal("not-a-number")).toBeNull();
    expect(parseDecimal("")).toBeNull();
  });
});

describe("formatMoney", () => {
  it("formats both first-class currencies with grouping", () => {
    // Exact separators are CLDR data; assert structure, not bytes.
    expect(formatMoney(1_234_567, "DKK")).toMatch(/1.234.567/);
    expect(formatMoney(1_234_567, "DKK")).toContain("kr");
    expect(formatMoney(1_234_567, "EUR")).toMatch(/1.234.567/);
    expect(formatMoney(1_234_567, "EUR")).toContain("€");
  });

  it("renders a placeholder for null", () => {
    expect(formatMoney(null, "EUR")).toBe("—");
  });
});

describe("formatCompact", () => {
  it("compacts large values", () => {
    expect(formatCompact(1_234_567)).toMatch(/^1[.,]2\s?M$/);
    expect(formatCompact(950)).toBe("950");
  });
});

describe("formatShare", () => {
  it("formats 0..1 shares as percentages", () => {
    const formatted = formatShare(0.4694);
    expect(formatted).toMatch(/^46[.,]9/);
    expect(formatted).toContain("%");
  });

  it("renders a placeholder for null", () => {
    expect(formatShare(null)).toBe("—");
  });
});

describe("iso dates", () => {
  it("formats ISO dates", () => {
    expect(isoDate(new Date(Date.UTC(2026, 0, 15)))).toBe("2026-01-15");
  });

  it("computes days-ago windows deterministically", () => {
    const today = new Date(Date.UTC(2026, 0, 31));
    expect(isoDaysAgo(30, today)).toBe("2026-01-01");
  });
});
