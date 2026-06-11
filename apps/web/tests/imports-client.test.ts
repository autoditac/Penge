/** Pagination behavior of `fetchImportSession` (review fix for PR #217).
 *
 * The API caps each page at `limit` rows; the client must keep fetching until
 * it holds `total_rows` rows so commit gating never sees a partial page.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchImportSession } from "../src/api/client";
import type { ImportRow, ImportSessionWithRows } from "../src/api/schemas";

function makeRow(index: number): ImportRow {
  return {
    edited: false,
    excluded: false,
    id: `row-${String(index)}`,
    issues: [],
    kind: "transaction",
    payload: { amount: "1.00" },
    row_index: index,
    status: "ok",
  };
}

function makePage(rows: readonly ImportRow[], totalRows: number): ImportSessionWithRows {
  return {
    committed_at: null,
    content_sha256: "ab".repeat(32),
    created_at: "2026-02-01T08:00:00Z",
    error: null,
    expires_at: "2026-02-03T08:00:00Z",
    id: "session-1",
    original_filename: "statement.csv",
    params: {},
    row_counts: { error: 0, excluded: 0, ok: totalRows, total: totalRows, warning: 0 },
    rows: [...rows],
    source: "nordnet",
    status: "staged",
    total_rows: totalRows,
    updated_at: "2026-02-01T08:00:00Z",
  };
}

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchImportSession pagination", () => {
  it("returns a single page untouched when total_rows fits in one page", async () => {
    const rows = [makeRow(0), makeRow(1)];
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(makePage(rows, 2)));
    vi.stubGlobal("fetch", fetchMock);

    const session = await fetchImportSession("session-1");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(session.rows).toHaveLength(2);
    expect(session.total_rows).toBe(2);
  });

  it("follows offset pagination until all rows are loaded", async () => {
    const totalRows = 2_500;
    const allRows = Array.from({ length: totalRows }, (_, index) => makeRow(index));
    const fetchMock = vi.fn().mockImplementation((url: URL) => {
      const offset = Number(url.searchParams.get("offset"));
      const limit = Number(url.searchParams.get("limit"));
      const page = allRows.slice(offset, offset + limit);
      return Promise.resolve(jsonResponse(makePage(page, totalRows)));
    });
    vi.stubGlobal("fetch", fetchMock);

    const session = await fetchImportSession("session-1");

    expect(fetchMock).toHaveBeenCalledTimes(3); // 1000 + 1000 + 500
    expect(session.rows).toHaveLength(totalRows);
    expect(session.rows[0]?.id).toBe("row-0");
    expect(session.rows[totalRows - 1]?.id).toBe(`row-${String(totalRows - 1)}`);
  });

  it("stops when a follow-up page is empty instead of looping forever", async () => {
    const rows = Array.from({ length: 1_000 }, (_, index) => makeRow(index));
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(makePage(rows, 5_000)))
      .mockResolvedValue(jsonResponse(makePage([], 5_000)));
    vi.stubGlobal("fetch", fetchMock);

    const session = await fetchImportSession("session-1");

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(session.rows).toHaveLength(1_000);
  });
});
