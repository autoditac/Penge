import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    environment: "node",
    globals: false,
    setupFiles: ["tests/setup-dom.ts"],
    // The first MUI/Emotion render in a jsdom test file pays a cold-start
    // cost that exceeds Vitest's 5s default on the shared self-hosted runner
    // (observed 6.1s), which skipped image publishing on main. 20s keeps real
    // hangs detectable while removing load-dependent flakes.
    testTimeout: 20_000,
  },
});
