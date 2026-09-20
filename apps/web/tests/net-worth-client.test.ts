import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchAllNetWorthByAccount } from "../src/api/client";

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function point(accountId: string, asOf: string) {
  return {
    account_currency: "EUR",
    account_id: accountId,
    as_of: asOf,
    balance_acct_ccy: "100.0000",
    balance_dkk: "746.0000",
    balance_eur: "100.0000",
    entity_id: "entity-1",
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchAllNetWorthByAccount", () => {
  it("follows offset pagination until all account points are loaded", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          limit: 2,
          offset: 0,
          points: [point("a1", "2026-01-01"), point("a2", "2026-01-01")],
          total: 3,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          limit: 2,
          offset: 2,
          points: [point("a1", "2026-01-02")],
          total: 3,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAllNetWorthByAccount({ since: "2026-01-01", limit: 2 });

    expect(result.points).toHaveLength(3);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const secondUrl = fetchMock.mock.calls[1]?.[0];
    expect(secondUrl).toBeInstanceOf(URL);
    expect((secondUrl as URL).searchParams.get("offset")).toBe("2");
  });
});
