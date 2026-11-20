import { defineConfig, devices } from "@playwright/test";

import { apiPort, apiUrl, webPort, webUrl } from "./browser-env";

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: "line",
  use: {
    baseURL: webUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [
    {
      command: `uv run --project ../.. --group api --group db --group http --group parsers --group manual --group enablebanking penge-api --host 127.0.0.1 --port ${apiPort}`,
      url: `${apiUrl}/openapi.json`,
      reuseExistingServer: false,
      env: { PENGE_API_CORS_ORIGINS: webUrl },
    },
    {
      command: `pnpm exec vite build --mode e2e && pnpm exec vite preview --host 127.0.0.1 --port ${webPort} --strictPort`,
      url: webUrl,
      reuseExistingServer: false,
      env: { VITE_PENGE_DEMO: "false", VITE_PENGE_API_URL: apiUrl },
    },
  ],
});
