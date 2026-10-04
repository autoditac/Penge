import { chmodSync, closeSync, constants, mkdirSync, openSync, statSync, writeSync } from "node:fs";
import { join } from "node:path";

const SAFE_ARGUMENT_KEY = /^[A-Za-z0-9_.-]{1,64}$/;
const MAX_ARGUMENT_KEYS = 32;

export interface AuditRecord {
  ts: string;
  tool: string;
  argumentKeys: string[];
  actorId?: string;
  sessionId?: string;
  status: "ok" | "error";
  durationMs: number;
  error?: string;
}

export function auditArgumentKeys(input: unknown): string[] {
  if (input === null || typeof input !== "object") return [];
  const keys: string[] = [];
  for (const key of Object.keys(input)) {
    if (SAFE_ARGUMENT_KEY.test(key)) keys.push(key);
    if (keys.length === MAX_ARGUMENT_KEYS) break;
  }
  return keys.sort();
}

export interface AuditLogger {
  record(
    entry: Omit<AuditRecord, "ts" | "argumentKeys"> & {
      args: unknown;
    },
  ): void;
  close(): Promise<void>;
}

export interface AuditLoggerOptions {
  logDir: string;
  /** Explicit opt-in mirror for operators that have reviewed the sink. */
  stderr?: NodeJS.WritableStream;
  /** Override the date used for the file name (test determinism). */
  now?: () => Date;
  /** Opaque per-person identifier. Must not contain a name or email address. */
  actorId?: string;
  /** Opaque bounded-lifetime chat session identifier. */
  sessionId?: string;
}

export function createAuditLogger(opts: AuditLoggerOptions): AuditLogger {
  const now = opts.now ?? (() => new Date());
  const datePart = now().toISOString().slice(0, 10);
  const filePath = join(opts.logDir, `audit-${datePart}.jsonl`);
  mkdirSync(opts.logDir, { recursive: true, mode: 0o700 });
  chmodSync(opts.logDir, 0o700);
  if ((statSync(opts.logDir).mode & 0o077) !== 0) {
    throw new Error("MCP audit directory permissions must be 0700");
  }
  const file = openSync(
    filePath,
    constants.O_APPEND | constants.O_CREAT | constants.O_WRONLY,
    0o600,
  );
  chmodSync(filePath, 0o600);
  if ((statSync(filePath).mode & 0o077) !== 0) {
    closeSync(file);
    throw new Error("MCP audit file permissions must be 0600");
  }
  let closed = false;

  return {
    record(entry) {
      if (closed) throw new Error("MCP audit logger is closed");
      const record: AuditRecord = {
        ts: now().toISOString(),
        ...(opts.actorId === undefined ? {} : { actorId: opts.actorId }),
        ...(opts.sessionId === undefined ? {} : { sessionId: opts.sessionId }),
        tool: entry.tool,
        argumentKeys: auditArgumentKeys(entry.args),
        status: entry.status,
        durationMs: entry.durationMs,
        ...(entry.error === undefined ? {} : { error: entry.error }),
      };
      const line = `${JSON.stringify(record)}\n`;
      writeSync(file, line);
      opts.stderr?.write(line);
    },
    async close() {
      if (!closed) {
        closeSync(file);
        closed = true;
      }
    },
  };
}
