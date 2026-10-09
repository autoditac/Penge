import { describe, expect, it, vi } from "vitest";

import { closeServiceResources } from "../src/lifecycle.js";

describe("chat service lifecycle", () => {
  it("closes the store when server cleanup rejects", async () => {
    const server = {
      close: vi.fn(async () => {
        throw new Error("synthetic server cleanup failure");
      }),
    };
    const store = { close: vi.fn(async () => undefined) };

    await expect(closeServiceResources(server, store)).rejects.toThrow(
      /chat service shutdown failed/,
    );
    expect(server.close).toHaveBeenCalledOnce();
    expect(store.close).toHaveBeenCalledOnce();
  });
});
