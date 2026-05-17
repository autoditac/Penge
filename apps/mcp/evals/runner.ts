/**
 * Vitest harness for the MCP golden-question eval suite.
 *
 * Each golden in `goldens.ts` is exposed as an individual `it()` so
 * vitest reports one row per question with the full question text and
 * id in the title. A failing golden re-throws with the rationale
 * appended so the diff in CI logs has enough context to triage
 * without scrolling back to the dataset.
 *
 * This file is **not** picked up by the default `vitest run` include
 * glob (so `pnpm --filter @penge/mcp test` stays fast and focused on
 * unit tests). It is invoked explicitly by `just mcp-evals` and the
 * dedicated CI workflow via `vitest run evals/runner.ts`.
 */

import { describe, expect, it } from "vitest";

import { formatGoldenFailure } from "./format.js";
import { GOLDENS } from "./goldens.js";

describe("MCP golden questions (23)", () => {
  it("dataset is the right size and shape", () => {
    expect(GOLDENS).toHaveLength(23);
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
