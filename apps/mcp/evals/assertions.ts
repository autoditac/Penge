/**
 * Assertion helpers for the golden-question MCP eval harness.
 *
 * Each helper throws a plain `Error` with a structured message on
 * failure. The runner catches these and re-throws with the question
 * text + rationale prepended, so vitest reports the failure with
 * full context.
 */

export function approxEqual(
  actual: number,
  expected: number,
  toleranceFraction: number,
  label: string,
): void {
  if (!Number.isFinite(actual) || !Number.isFinite(expected)) {
    throw new Error(
      `${label}: expected finite numbers, got actual=${actual}, expected=${expected}`,
    );
  }
  const diff = Math.abs(actual - expected);
  const limit = Math.abs(expected) * toleranceFraction;
  if (diff > limit) {
    const pct = expected === 0 ? "∞" : ((diff / Math.abs(expected)) * 100).toFixed(3);
    throw new Error(
      `${label}: expected ${expected} ± ${(toleranceFraction * 100).toFixed(2)}%, ` +
        `got ${actual} (off by ${diff}, ${pct} %)`,
    );
  }
}

export function expectFiniteNonNegative(value: number, label: string): void {
  if (!Number.isFinite(value) || value < 0) {
    throw new Error(`${label}: expected finite non-negative, got ${value}`);
  }
}

export interface PercentileSummary {
  p10: Record<string, number>;
  p50: Record<string, number>;
  p90: Record<string, number>;
}

/**
 * Verify the p10 ≤ p50 ≤ p90 ordering invariant for every year present
 * in any of the three percentile dictionaries.
 */
export function expectPercentileOrdering(summary: PercentileSummary, label: string): void {
  const years = new Set<string>([
    ...Object.keys(summary.p10),
    ...Object.keys(summary.p50),
    ...Object.keys(summary.p90),
  ]);
  for (const year of years) {
    const p10 = summary.p10[year];
    const p50 = summary.p50[year];
    const p90 = summary.p90[year];
    if (p10 === undefined || p50 === undefined || p90 === undefined) {
      throw new Error(`${label}: year ${year} missing from one of p10/p50/p90`);
    }
    if (!(p10 <= p50 && p50 <= p90)) {
      throw new Error(
        `${label}: year ${year} violates p10 ≤ p50 ≤ p90 ` + `(p10=${p10}, p50=${p50}, p90=${p90})`,
      );
    }
  }
}

/**
 * Patterns the redactor in `apps/mcp/src/redact.ts` is responsible
 * for masking. Used by the vault-search "never leaks raw account
 * numbers" golden.
 */
const RAW_LEAK_PATTERNS: { pattern: RegExp; name: string }[] = [
  { pattern: /\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b/i, name: "IBAN-contiguous" },
  {
    pattern: /\b[A-Z]{2}\d{2}(?:[ -][A-Z0-9]{4}){2,7}[ -][A-Z0-9]{1,4}\b/i,
    name: "IBAN-grouped",
  },
  { pattern: /\b\d{6}-?\d{4}\b/, name: "CPR" },
  { pattern: /\b\d{8,}\b/, name: "long-digit-run" },
];

export function expectNoRawAccountLeak(excerpt: string, label: string): void {
  for (const { pattern, name } of RAW_LEAK_PATTERNS) {
    if (pattern.test(excerpt)) {
      throw new Error(`${label}: excerpt leaks raw ${name} value: ${JSON.stringify(excerpt)}`);
    }
  }
}

export function expectSumCloseTo(
  values: readonly number[],
  expected: number,
  toleranceFraction: number,
  label: string,
): void {
  const sum = values.reduce((acc, v) => acc + v, 0);
  approxEqual(sum, expected, toleranceFraction, label);
}
