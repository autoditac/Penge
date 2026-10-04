import { describe, expect, it, vi } from "vitest";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { PassThrough } from "node:stream";

import { auditArgumentKeys, createAuditLogger } from "../src/audit.js";

const SCRATCH_ROOT = join(process.cwd(), "tests", ".scratch");
mkdirSync(SCRATCH_ROOT, { recursive: true });

describe("auditArgumentKeys", () => {
  it("returns sorted top-level keys without values or nested field names", () => {
    expect(
      auditArgumentKeys({
        transaction_id: "11111111-1111-4111-8111-111111111111",
        query: "private search",
        nested: { prompt: "private prompt" },
      }),
    ).toEqual(["nested", "query", "transaction_id"]);
  });

  it("returns no keys for non-object inputs", () => {
    expect(auditArgumentKeys(null)).toEqual([]);
    expect(auditArgumentKeys("private")).toEqual([]);
    expect(auditArgumentKeys(42)).toEqual([]);
  });
});

describe("createAuditLogger", () => {
  it("writes keys-only JSONL with restrictive permissions and an explicitly opted-in sink", async () => {
    const dir = mkdtempSync(join(SCRATCH_ROOT, "audit-"));
    const stderr = new PassThrough();
    const chunks: Buffer[] = [];
    stderr.on("data", (chunk: Buffer) => chunks.push(chunk));

    const fixedDate = new Date("2026-05-10T12:34:56.000Z");
    const logger = createAuditLogger({
      logDir: dir,
      stderr,
      now: () => fixedDate,
      actorId: "actor_01hx9p",
      sessionId: "session_01hx9p",
    });

    logger.record({
      tool: "get_household_transaction_detail",
      args: {
        transaction_id: "11111111-1111-4111-8111-111111111111",
        query: "private search value",
        prompt: "private prompt",
      },
      status: "ok",
      durationMs: 12,
    });
    await logger.close();

    const filePath = join(dir, "audit-2026-05-10.jsonl");
    const fileText = readFileSync(filePath, "utf8").trim();
    const stderrText = Buffer.concat(chunks).toString("utf8").trim();
    for (const text of [fileText, stderrText]) {
      expect(text).toContain('"tool":"get_household_transaction_detail"');
      expect(text).toContain('"argumentKeys":["prompt","query","transaction_id"]');
      expect(text).not.toContain("11111111-1111-4111-8111-111111111111");
      expect(text).not.toContain("private search value");
      expect(text).not.toContain("private prompt");
    }

    const parsed = JSON.parse(fileText) as Record<string, unknown>;
    expect(parsed.ts).toBe("2026-05-10T12:34:56.000Z");
    expect(parsed.actorId).toBe("actor_01hx9p");
    expect(parsed.sessionId).toBe("session_01hx9p");
    expect(statSync(dir).mode & 0o777).toBe(0o700);
    expect(statSync(filePath).mode & 0o777).toBe(0o600);

    rmSync(dir, { recursive: true, force: true });
  });

  it("does not duplicate audit records to process stderr by default", async () => {
    const dir = mkdtempSync(join(SCRATCH_ROOT, "audit-"));
    const writeSpy = vi.spyOn(process.stderr, "write");
    const logger = createAuditLogger({
      logDir: dir,
      now: () => new Date("2026-05-10T12:34:56.000Z"),
    });

    logger.record({ tool: "_meta", args: { query: "private" }, status: "ok", durationMs: 1 });
    await logger.close();

    expect(writeSpy).not.toHaveBeenCalled();
    writeSpy.mockRestore();
    rmSync(dir, { recursive: true, force: true });
  });

  it("surfaces audit-path creation errors", () => {
    const dir = mkdtempSync(join(SCRATCH_ROOT, "audit-"));
    const filePath = join(dir, "not-a-directory");
    writeFileSync(filePath, "occupied");
    expect(() => createAuditLogger({ logDir: filePath })).toThrow();
    rmSync(dir, { recursive: true, force: true });
  });
});
