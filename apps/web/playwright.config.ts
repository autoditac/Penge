import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [
    {
      command:
        "uv run --project ../.. --group api --group db --group http --group parsers --group manual --group enablebanking penge-api",
      url: "http://127.0.0.1:8000/openapi.json",
      reuseExistingServer: false,
    },
    {
      command: "pnpm build && pnpm exec vite preview --host 127.0.0.1 --port 5173",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: false,
      env: { VITE_PENGE_DEMO: "false", VITE_PENGE_API_URL: "http://127.0.0.1:8000" },
    },
  ],
});
