import { describe, expect, it } from "vitest";

import { redactTextBounded } from "../src/redact.js";

describe("redactTextBounded", () => {
  it("reapplies the wire bound after redaction expands a value", () => {
    const value = `${"x".repeat(191)} 12345678`;
    const redacted = redactTextBounded(value, 200);
    expect(redacted).toHaveLength(200);
    expect(redacted).not.toContain("12345678");
  });

  it("does not split a surrogate pair at the output boundary", () => {
    expect(redactTextBounded(`${"x".repeat(199)}😀`, 200)).toBe("x".repeat(199));
  });
});
