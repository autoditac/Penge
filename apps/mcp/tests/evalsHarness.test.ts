import { describe, expect, it } from "vitest";

import {
  approxEqual,
  expectFiniteNonNegative,
  expectNoRawAccountLeak,
  expectPercentileOrdering,
  expectSumCloseTo,
} from "../evals/assertions.js";
import { formatGoldenFailure } from "../evals/runner.js";
import type { Golden } from "../evals/goldens.js";
import { buildVault, SYNTHETIC_VAULT_DOCS } from "../evals/fixtures/vaultDocs.js";
import { mkdtempSync, readFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

describe("approxEqual", () => {
  it("passes within tolerance", () => {
    expect(() => approxEqual(100, 100.4, 0.01, "lbl")).not.toThrow();
  });

  it("throws outside tolerance with a structured message", () => {
    expect(() => approxEqual(100, 110, 0.01, "lbl")).toThrow(/lbl: expected 110.*got 100/);
  });

  it("rejects NaN / Infinity", () => {
    expect(() => approxEqual(Number.NaN, 1, 0.01, "lbl")).toThrow(/finite/);
    expect(() => approxEqual(1, Number.POSITIVE_INFINITY, 0.01, "lbl")).toThrow(/finite/);
  });

  it("treats expected=0 as exact match required (limit=0)", () => {
    expect(() => approxEqual(0, 0, 0.01, "lbl")).not.toThrow();
    expect(() => approxEqual(0.1, 0, 0.01, "lbl")).toThrow();
  });
});

describe("expectFiniteNonNegative", () => {
  it("accepts 0 and positive finite numbers", () => {
    expect(() => expectFiniteNonNegative(0, "x")).not.toThrow();
    expect(() => expectFiniteNonNegative(42.5, "x")).not.toThrow();
  });
  it("rejects negative and non-finite", () => {
    expect(() => expectFiniteNonNegative(-1, "x")).toThrow();
    expect(() => expectFiniteNonNegative(Number.NaN, "x")).toThrow();
  });
});

describe("expectPercentileOrdering", () => {
  it("accepts ordered summaries", () => {
    expect(() =>
      expectPercentileOrdering(
        { p10: { "2030": 1 }, p50: { "2030": 2 }, p90: { "2030": 3 } },
        "ok",
      ),
    ).not.toThrow();
  });

  it("rejects p10 > p50", () => {
    expect(() =>
      expectPercentileOrdering(
        { p10: { "2030": 5 }, p50: { "2030": 2 }, p90: { "2030": 3 } },
        "bad",
      ),
    ).toThrow(/violates p10/);
  });

  it("rejects p50 > p90", () => {
    expect(() =>
      expectPercentileOrdering(
        { p10: { "2030": 1 }, p50: { "2030": 4 }, p90: { "2030": 3 } },
        "bad",
      ),
    ).toThrow(/violates p10/);
  });

  it("rejects missing years", () => {
    expect(() =>
      expectPercentileOrdering({ p10: { "2030": 1 }, p50: {}, p90: { "2030": 3 } }, "bad"),
    ).toThrow(/missing/);
  });
});

describe("expectNoRawAccountLeak", () => {
  it("flags a contiguous IBAN", () => {
    expect(() => expectNoRawAccountLeak("Saldo DE89370400440532013000 OK", "l")).toThrow(/IBAN/);
  });
  it("flags a DK CPR", () => {
    expect(() => expectNoRawAccountLeak("Borger 010190-1234", "l")).toThrow(/CPR/);
  });
  it("flags long digit runs", () => {
    expect(() => expectNoRawAccountLeak("Sagsnr 99887766554433", "l")).toThrow(/long-digit-run/);
  });
  it("passes for redacted excerpts", () => {
    expect(() => expectNoRawAccountLeak("Saldo [REDACTED] OK CPR: [REDACTED].", "l")).not.toThrow();
  });
});

describe("expectSumCloseTo", () => {
  it("passes when sum is within tolerance", () => {
    expect(() => expectSumCloseTo([1, 2, 3], 6, 0.0001, "sum")).not.toThrow();
  });
  it("fails when sum drifts beyond tolerance", () => {
    expect(() => expectSumCloseTo([1, 2, 3], 10, 0.001, "sum")).toThrow();
  });
});

describe("formatGoldenFailure", () => {
  it("wraps the cause with id, tool, question, rationale", () => {
    const golden = {
      id: "g-1",
      question: "Is the sky blue?",
      rationale: "Because rayleigh scattering.",
      tool: "query_net_worth",
      run: async () => undefined,
    } as Golden;
    const cause = new Error("color was red");
    const err = formatGoldenFailure(golden, cause);
    expect(err.message).toContain("Golden g-1 (query_net_worth) failed");
    expect(err.message).toContain("Is the sky blue?");
    expect(err.message).toContain("rayleigh");
    expect(err.message).toContain("color was red");
  });
  it("handles non-Error causes", () => {
    const golden = {
      id: "g-2",
      question: "?",
      rationale: "?",
      tool: "query_net_worth",
      run: async () => undefined,
    } as Golden;
    const err = formatGoldenFailure(golden, "string cause");
    expect(err.message).toContain("string cause");
  });
});

describe("buildVault fixture loader", () => {
  it("writes an index file and OCR sidecars for each document", () => {
    const root = mkdtempSync(join(tmpdir(), "penge-eval-test-vault-"));
    try {
      buildVault(root, SYNTHETIC_VAULT_DOCS);
      const indexPath = join(root, ".index.json");
      expect(existsSync(indexPath)).toBe(true);
      const parsed = JSON.parse(readFileSync(indexPath, "utf-8")) as Record<
        string,
        { path: string; size: number; filed_at: string }
      >;
      expect(Object.keys(parsed)).toHaveLength(SYNTHETIC_VAULT_DOCS.length);
      for (const doc of SYNTHETIC_VAULT_DOCS) {
        expect(parsed[doc.hash]?.path).toBe(doc.relPath);
        const lastSlash = doc.relPath.lastIndexOf("/");
        const fileName = doc.relPath.slice(lastSlash + 1);
        const stem = fileName.slice(0, fileName.lastIndexOf("."));
        const dir = doc.relPath.slice(0, lastSlash);
        const sidecar = join(root, dir, `${stem}.txt`);
        expect(existsSync(sidecar)).toBe(true);
        expect(readFileSync(sidecar, "utf-8")).toBe(doc.ocr);
      }
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
