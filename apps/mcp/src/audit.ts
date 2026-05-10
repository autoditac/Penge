import { mkdirSync, createWriteStream, type WriteStream } from "node:fs";
import { dirname, join } from "node:path";

const REDACT_KEY = /(account|iban|cpr|tax[_-]?id|name|email)/i;
const REDACTED = "[REDACTED]";

export interface AuditRecord {
  ts: string;
  tool: string;
  args: unknown;
  status: "ok" | "error";
  durationMs: number;
  error?: string;
}

/**
 * Recursively walk an unknown value and replace every value whose key matches
 * REDACT_KEY with "[REDACTED]". Arrays are walked element-wise. Primitive
 * values at the root return unchanged — redaction only applies inside objects
 * because we key off field names.
 */
export function redactArgs(input: unknown): unknown {
  if (Array.isArray(input)) {
    return input.map((item) => redactArgs(item));
  }
  if (input !== null && typeof input === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(input as Record<string, unknown>)) {
      if (REDACT_KEY.test(key)) {
        out[key] = REDACTED;
      } else {
        out[key] = redactArgs(value);
      }
    }
    return out;
  }
  return input;
}

export interface AuditLogger {
  record(entry: Omit<AuditRecord, "ts">): void;
  close(): Promise<void>;
}

export interface AuditLoggerOptions {
  logDir: string;
  /** Override stderr stream (test injection). */
  stderr?: NodeJS.WritableStream;
  /** Override the date used for the file name (test determinism). */
  now?: () => Date;
}

export function createAuditLogger(opts: AuditLoggerOptions): AuditLogger {
  const now = opts.now ?? (() => new Date());
  const stderr: NodeJS.WritableStream = opts.stderr ?? process.stderr;
  const datePart = now().toISOString().slice(0, 10);
  const filePath = join(opts.logDir, `audit-${datePart}.jsonl`);
  mkdirSync(dirname(filePath), { recursive: true });
  const file: WriteStream = createWriteStream(filePath, { flags: "a" });

  return {
    record(entry) {
      const record: AuditRecord = {
        ts: now().toISOString(),
        ...entry,
        args: redactArgs(entry.args),
      };
      const line = `${JSON.stringify(record)}\n`;
      file.write(line);
      stderr.write(line);
    },
    async close() {
      await new Promise<void>((resolve) => {
        file.end(() => resolve());
      });
    },
  };
}
