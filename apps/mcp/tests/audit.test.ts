import { describe, expect, it } from "vitest";
import { mkdtempSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { PassThrough } from "node:stream";

import { createAuditLogger, redactArgs } from "../src/audit.js";

const SCRATCH_ROOT = join(process.cwd(), "tests", ".scratch");
mkdirSync(SCRATCH_ROOT, { recursive: true });

describe("redactArgs", () => {
  it("redacts top-level sensitive keys", () => {
    expect(
      redactArgs({
        account: "DK1234",
        iban: "DE89...",
        cpr: "010190-1234",
        tax_id: "12345678",
        name: "Rouven",
        email: "x@example.com",
        amount: 42,
      }),
    ).toEqual({
      account: "[REDACTED]",
      iban: "[REDACTED]",
      cpr: "[REDACTED]",
      tax_id: "[REDACTED]",
      name: "[REDACTED]",
      email: "[REDACTED]",
      amount: 42,
    });
  });

  it("redacts case-insensitively and across nested objects", () => {
    expect(
      redactArgs({
        Counterparty: { Name: "Acme", Country: "DK" },
        items: [{ Account_Number: "x", Memo: "rent" }],
      }),
    ).toEqual({
      Counterparty: { Name: "[REDACTED]", Country: "DK" },
      items: [{ Account_Number: "[REDACTED]", Memo: "rent" }],
    });
  });

  it("leaves primitives and unrelated structures untouched", () => {
    expect(redactArgs(42)).toBe(42);
    expect(redactArgs("hello")).toBe("hello");
    expect(redactArgs(null)).toBe(null);
    expect(redactArgs([1, 2, { amount: 3 }])).toEqual([1, 2, { amount: 3 }]);
  });
});

describe("createAuditLogger", () => {
  it("writes one redacted JSONL record per call to file and stderr", async () => {
    const dir = mkdtempSync(join(SCRATCH_ROOT, "audit-"));
    const stderr = new PassThrough();
    const chunks: Buffer[] = [];
    stderr.on("data", (c: Buffer) => chunks.push(c));

    const fixedDate = new Date("2026-05-10T12:34:56.000Z");
    const logger = createAuditLogger({
      logDir: dir,
      stderr,
      now: () => fixedDate,
    });

    logger.record({
      tool: "_meta",
      args: { account: "DK1", note: "ok" },
      status: "ok",
      durationMs: 12,
    });
    await logger.close();

    const stderrText = Buffer.concat(chunks).toString("utf8").trim();
    expect(stderrText).toContain('"tool":"_meta"');
    expect(stderrText).toContain('"account":"[REDACTED]"');
    expect(stderrText).toContain('"note":"ok"');

    const fileText = readFileSync(join(dir, "audit-2026-05-10.jsonl"), "utf8").trim();
    const parsed = JSON.parse(fileText) as Record<string, unknown>;
    expect(parsed.tool).toBe("_meta");
    expect(parsed.status).toBe("ok");
    expect(parsed.ts).toBe("2026-05-10T12:34:56.000Z");
    expect((parsed.args as Record<string, unknown>).account).toBe("[REDACTED]");

    rmSync(dir, { recursive: true, force: true });
  });
});
