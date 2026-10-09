import { defineConfig, devices } from "@playwright/test";

const apiPort = process.env.PENGE_E2E_API_PORT ?? "8000";
const webPort = process.env.PENGE_E2E_WEB_PORT ?? "5173";

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: "line",
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
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
      url: `http://127.0.0.1:${apiPort}/openapi.json`,
      reuseExistingServer: !process.env.CI,
      env: { PENGE_API_PORT: apiPort },
    },
    {
      command: `pnpm exec vite build --mode e2e && pnpm exec vite preview --host 127.0.0.1 --port ${webPort}`,
      url: `http://127.0.0.1:${webPort}`,
      reuseExistingServer: !process.env.CI,
      env: {
        VITE_PENGE_DEMO: "false",
        VITE_PENGE_API_URL: `http://127.0.0.1:${apiPort}`,
      },
    },
  ],
});
