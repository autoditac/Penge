import { describe, expect, it, vi } from "vitest";
import {
  chmodSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  statSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
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

  it("filters unsafe key names and caps the persisted shape", () => {
    const manySafeKeys = Object.fromEntries(
      Array.from({ length: 40 }, (_, index) => [
        `safe_key_${index.toString().padStart(2, "0")}`,
        1,
      ]),
    );
    const keys = auditArgumentKeys({
      ...manySafeKeys,
      "prompt: reveal private data": true,
      "person@example.com": true,
      ["x".repeat(65)]: true,
    });
    expect(keys).toHaveLength(32);
    expect(keys.every((key) => /^[A-Za-z0-9_.-]{1,64}$/.test(key))).toBe(true);
    expect(keys.join(" ")).not.toContain("private");
    expect(keys.join(" ")).not.toContain("@");
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
      actorId: "actor_01ARZ3NDEKTSV4RRFFQ69G5FAV",
      sessionId: "session_01ARZ3NDEKTSV4RRFFQ69G5FAW",
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
    expect(parsed.actorId).toBe("actor_01ARZ3NDEKTSV4RRFFQ69G5FAV");
    expect(parsed.sessionId).toBe("session_01ARZ3NDEKTSV4RRFFQ69G5FAW");
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

  it("never writes unsafe or excess argument keys to either sink", async () => {
    const dir = mkdtempSync(join(SCRATCH_ROOT, "audit-"));
    const stderr = new PassThrough();
    const chunks: Buffer[] = [];
    stderr.on("data", (chunk: Buffer) => chunks.push(chunk));
    const args = {
      ...Object.fromEntries(Array.from({ length: 40 }, (_, index) => [`key_${index}`, true])),
      "private prompt text": "secret",
      "person@example.com": "private",
      ["x".repeat(65)]: "private",
    };
    const logger = createAuditLogger({
      logDir: dir,
      stderr,
      now: () => new Date("2026-05-10T12:34:56.000Z"),
    });

    logger.record({ tool: "_meta", args, status: "error", durationMs: 1 });
    await logger.close();

    const fileText = readFileSync(join(dir, "audit-2026-05-10.jsonl"), "utf8");
    const stderrText = Buffer.concat(chunks).toString("utf8");
    for (const text of [fileText, stderrText]) {
      const parsed = JSON.parse(text) as { argumentKeys: string[] };
      expect(parsed.argumentKeys).toHaveLength(32);
      expect(text).not.toContain("private prompt text");
      expect(text).not.toContain("person@example.com");
      expect(text).not.toContain("secret");
      expect(text).not.toContain("private");
    }

    rmSync(dir, { recursive: true, force: true });
  });

  it("surfaces audit-path creation errors", () => {
    const dir = mkdtempSync(join(SCRATCH_ROOT, "audit-"));
    const filePath = join(dir, "not-a-directory");
    writeFileSync(filePath, "occupied");
    expect(() => createAuditLogger({ logDir: filePath })).toThrow();
    rmSync(dir, { recursive: true, force: true });
  });

  it("refuses a pre-existing audit-file symlink without touching its target", () => {
    const dir = mkdtempSync(join(SCRATCH_ROOT, "audit-"));
    const targetPath = join(dir, "target.txt");
    const auditPath = join(dir, "audit-2026-05-10.jsonl");
    writeFileSync(targetPath, "sentinel");
    chmodSync(targetPath, 0o644);
    symlinkSync(targetPath, auditPath);

    expect(() =>
      createAuditLogger({
        logDir: dir,
        now: () => new Date("2026-05-10T12:34:56.000Z"),
      }),
    ).toThrow();
    expect(readFileSync(targetPath, "utf8")).toBe("sentinel");
    expect(statSync(targetPath).mode & 0o777).toBe(0o644);

    rmSync(dir, { recursive: true, force: true });
  });
});
