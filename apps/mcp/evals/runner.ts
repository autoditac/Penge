/**
 * Vitest harness for the MCP golden-question eval suite.
 *
 * Each golden in `goldens.ts` is exposed as an individual `it()` so
 * vitest reports one row per question with the full question text and
 * id in the title. A failing golden re-throws with the rationale
 * appended so the diff in CI logs has enough context to triage
 * without scrolling back to the dataset.
 *
 * This file is its own vitest spec — see `vitest.config.ts` for the
 * include glob.
 */

import { describe, expect, it } from "vitest";

import { GOLDENS, type Golden } from "./goldens.js";

export function formatGoldenFailure(golden: Golden, cause: unknown): Error {
  const message = cause instanceof Error ? cause.message : String(cause);
  const wrapped = new Error(
    `Golden ${golden.id} (${golden.tool}) failed.\n` +
      `Question: ${golden.question}\n` +
      `Rationale: ${golden.rationale}\n` +
      `Failure : ${message}`,
  );
  if (cause instanceof Error && cause.stack !== undefined) {
    wrapped.stack = `${wrapped.message}\n${cause.stack}`;
  }
  return wrapped;
}

describe("MCP golden questions (20)", () => {
  it("dataset is the right size and shape", () => {
    expect(GOLDENS).toHaveLength(20);
    const ids = GOLDENS.map((g) => g.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const golden of GOLDENS) {
      expect(golden.question.length).toBeGreaterThan(10);
      expect(golden.rationale.length).toBeGreaterThan(10);
    }
  });

  for (const golden of GOLDENS) {
    it(`[${golden.id}] ${golden.question}`, async () => {
      try {
        await golden.run();
      } catch (cause) {
        throw formatGoldenFailure(golden, cause);
      }
    });
  }
});
