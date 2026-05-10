import { defineConfig } from "vitest/config";

// Standalone vitest config used by `just mcp-evals` and the
// dedicated CI workflow. Keeps the golden-question harness out of the
// default `pnpm test` run so unit tests stay fast and focused.
export default defineConfig({
  test: {
    include: ["evals/runner.ts"],
    environment: "node",
    globals: false,
  },
});
