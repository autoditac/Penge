import { afterEach, expect, test, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

async function config(apiPort?: string, webPort?: string) {
  vi.stubEnv("PENGE_BROWSER_API_PORT", apiPort);
  vi.stubEnv("PENGE_BROWSER_WEB_PORT", webPort);
  return (await import("../playwright.config")).default;
}

test.each([
  [undefined, undefined, 8000, 5173],
  ["18001", "15001", 18001, 15001],
  ["18002", "15002", 18002, 15002],
  ["18003", "15003", 18003, 15003],
])("browser servers and assertions share ports %s/%s", async (api, web, apiPort, webPort) => {
  const resolved = await config(api, web);
  const origins = await import("../browser-env");
  expect(origins.apiUrl).toBe(`http://127.0.0.1:${apiPort}`);
  expect(origins.webUrl).toBe(`http://127.0.0.1:${webPort}`);
  expect(resolved.use?.baseURL).toBe(origins.webUrl);
  expect(resolved.webServer).toEqual([
    expect.objectContaining({
      command: expect.stringContaining(`--host 127.0.0.1 --port ${apiPort}`),
      url: `${origins.apiUrl}/openapi.json`,
      reuseExistingServer: false,
      env: { PENGE_API_CORS_ORIGINS: origins.webUrl },
    }),
    expect.objectContaining({
      command: `pnpm exec vite preview --host 127.0.0.1 --port ${webPort} --strictPort`,
      url: origins.webUrl,
      reuseExistingServer: false,
      env: { VITE_PENGE_DEMO: "false", VITE_PENGE_API_URL: origins.apiUrl },
    }),
  ]);
});

test.each(["", "0", "65536", "18001.5", "not-a-port", "18001; exit 0"])(
  "invalid port %s fails rather than falling back or entering the server command",
  async (value) => {
    await expect(config(value, "15001")).rejects.toThrow();
    vi.resetModules();
    await expect(config("18001", value)).rejects.toThrow();
  },
);

test("API and preview cannot share one port", async () => {
  await expect(config("18001", "18001")).rejects.toThrow(
    "Browser API and preview ports must be different",
  );
});
