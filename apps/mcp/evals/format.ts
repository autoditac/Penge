/**
 * Failure formatter for the MCP golden-question harness.
 *
 * Lives in its own module (separate from `runner.ts`) so unit tests
 * and other callers can import it without picking up the
 * top-level vitest `describe`/`it` blocks declared in the runner.
 */

import type { Golden } from "./goldens.js";

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
