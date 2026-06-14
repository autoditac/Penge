/** Client + demo-store behavior for the bank-connections surface (#230).
 *
 * Verifies the typed client validates responses, sends the right bodies, maps
 * a 503 to a disabled-feature error, and that the deterministic demo store
 * walks link → authorize → sync without a backend.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  authorizeConnection,
  fetchConnections,
  startConnectionLink,
  syncConnection,
} from "../src/api/client";
import type { Connection } from "../src/api/schemas";
import { PengeApiError } from "../src/errors";

function connection(overrides: Partial<Connection> = {}): Connection {
  return {
    accounts: [],
    aspsp_country: "DE",
    aspsp_name: "GLS Gemeinschaftsbank",
    created_at: "2026-06-01T09:00:00Z",
    entity_name: "Rouven",
    id: "00000000-0000-0000-0000-000000000001",
    last_error: null,
    last_sync_at: null,
    last_sync_status: null,
    provider: "gls",
    status: "authorized",
    updated_at: "2026-06-01T09:00:00Z",
    valid_until: "2026-11-28T09:00:00Z",
    ...overrides,
  };
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("connections client", () => {
  it("validates and returns the connection list", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({ connections: [connection()] }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchConnections();

    expect(result.connections).toHaveLength(1);
    expect(result.connections[0]?.aspsp_name).toBe("GLS Gemeinschaftsbank");
  });

  it("posts the provider + entity name when starting a link", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        connection_id: "00000000-0000-0000-0000-000000000001",
        consent_url: "https://auth.example/start",
        state: "state-1",
        valid_until: "2026-11-28T09:00:00Z",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await startConnectionLink("gls", "Rouven");

    expect(result.consent_url).toBe("https://auth.example/start");
    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(JSON.parse(String(init.body))).toStrictEqual({
      provider: "gls",
      entity_name: "Rouven",
    });
  });

  it("omits an empty state when authorizing", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(connection()));
    vi.stubGlobal("fetch", fetchMock);

    await authorizeConnection({ code: "abc", state: "" });

    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(JSON.parse(String(init.body))).toStrictEqual({ code: "abc" });
  });

  it("surfaces a 503 as a disabled-feature PengeApiError", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: "Bank connections are disabled" }, 503));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchConnections()).rejects.toMatchObject({ status: 503 });
    await expect(fetchConnections()).rejects.toBeInstanceOf(PengeApiError);
  });

  it("passes the days query parameter when syncing", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ connection: connection(), transactions: 5, holding_snapshots: 1 }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await syncConnection("00000000-0000-0000-0000-000000000001", 30);

    const [url] = fetchMock.mock.calls[0] as [URL];
    expect(url.searchParams.get("days")).toBe("30");
  });
});

describe("connections demo store", () => {
  it("walks link → authorize → sync deterministically", async () => {
    const store = await import("../src/demo/connectionsStore");

    expect(store.demoListAspsps().providers.map((p) => p.provider)).toStrictEqual([
      "gls",
      "ebank",
      "lunar",
    ]);

    const link = store.demoStartLink("gls", "Rouven");
    expect(link.consent_url).toContain(link.state);

    const authorized = store.demoAuthorize({ code: "demo-code", state: link.state });
    expect(authorized.status).toBe("authorized");
    expect(authorized.accounts.length).toBeGreaterThan(0);

    const synced = store.demoSync(link.connection_id);
    expect(synced.transactions).toBeGreaterThan(0);
    expect(synced.connection.last_sync_status).toBe("ok");
  });

  it("rejects an unknown provider", async () => {
    const store = await import("../src/demo/connectionsStore");
    expect(() => store.demoStartLink("monzo", "Rouven")).toThrow();
  });
});
