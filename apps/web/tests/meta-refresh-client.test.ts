/** Client behavior for the WebUI-triggered dbt refresh (issue #285).
 *
 * Verifies the typed client posts to `/meta/refresh` with no body and
 * validates the response, and that lock-contention/dbt-failure responses
 * surface as a `PengeApiError` carrying the sanitized HTTP status.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { triggerMetaRefresh } from "../src/api/client";
import { PengeApiError } from "../src/errors";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("triggerMetaRefresh", () => {
  it("posts to /meta/refresh and returns the validated response", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ status: "succeeded", completed_at: "2026-06-01T09:00:00Z" }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await triggerMetaRefresh();

    expect(result).toStrictEqual({ status: "succeeded", completed_at: "2026-06-01T09:00:00Z" });
    const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(url.pathname).toBe("/meta/refresh");
    expect(init.method).toBe("POST");
  });

  it("surfaces lock contention as a 503 PengeApiError", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: "Refresh already in progress" }, 503));
    vi.stubGlobal("fetch", fetchMock);

    await expect(triggerMetaRefresh()).rejects.toMatchObject({
      status: 503,
      message: "Refresh already in progress",
    });
    await expect(triggerMetaRefresh()).rejects.toBeInstanceOf(PengeApiError);
  });

  it("surfaces a dbt build failure as a 502 PengeApiError", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: "dbt build failed" }, 502));
    vi.stubGlobal("fetch", fetchMock);

    await expect(triggerMetaRefresh()).rejects.toMatchObject({ status: 502 });
  });
});
