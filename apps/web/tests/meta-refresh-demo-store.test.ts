/** Demo-store behavior for the WebUI-triggered dbt refresh (issue #285).
 *
 * Verifies the demo implementation is deterministic — it must always
 * succeed with a fixed timestamp rather than calling the real API.
 */

import { describe, expect, it } from "vitest";

import { demoMetaRefresh } from "../src/demo/metaRefreshStore";

describe("demo meta-refresh store", () => {
  it("always resolves the same deterministic success payload", () => {
    const first = demoMetaRefresh();
    const second = demoMetaRefresh();

    expect(first).toStrictEqual({ status: "succeeded", completed_at: "2026-06-01T09:00:00Z" });
    expect(second).toStrictEqual(first);
  });
});
