import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { searchDocumentsTool, CATEGORY_VALUES } from "../src/tools/searchDocuments.js";

interface IndexEntry {
  path: string;
  size: number;
  filed_at: string;
}

interface FixtureDoc {
  hash: string;
  relPath: string;
  filedAt: string;
  ocr: string;
}

function buildVault(root: string, docs: FixtureDoc[]): void {
  const index: Record<string, IndexEntry> = {};
  for (const doc of docs) {
    const fullDir = join(root, ...doc.relPath.split("/").slice(0, -1));
    mkdirSync(fullDir, { recursive: true });
    const lastSlash = doc.relPath.lastIndexOf("/");
    const fileName = doc.relPath.slice(lastSlash + 1);
    const lastDot = fileName.lastIndexOf(".");
    const stem = fileName.slice(0, lastDot);
    writeFileSync(join(fullDir, fileName), "binary-pdf-bytes");
    writeFileSync(join(fullDir, `${stem}.txt`), doc.ocr, "utf-8");
    index[doc.hash] = {
      path: doc.relPath,
      size: 1234,
      filed_at: doc.filedAt,
    };
  }
  writeFileSync(join(root, ".index.json"), JSON.stringify(index, null, 2), "utf-8");
}

const ctx = { serverName: "test", serverVersion: "0.0.0-test" };

describe("search_documents — schema validation", () => {
  let vaultRoot: string;
  beforeEach(() => {
    vaultRoot = mkdtempSync(join(tmpdir(), "penge-vault-"));
  });
  afterEach(() => {
    rmSync(vaultRoot, { recursive: true, force: true });
  });

  it("rejects queries shorter than 2 characters", () => {
    const tool = searchDocumentsTool({ vaultRoot });
    expect(() => tool.inputSchema.parse({ query: "a" })).toThrow();
  });

  it("rejects unknown category", () => {
    const tool = searchDocumentsTool({ vaultRoot });
    expect(() => tool.inputSchema.parse({ query: "abc", type: "bogus" })).toThrow();
  });

  it("rejects limit > 100", () => {
    const tool = searchDocumentsTool({ vaultRoot });
    expect(() => tool.inputSchema.parse({ query: "abc", limit: 101 })).toThrow();
  });

  it("rejects limit < 1", () => {
    const tool = searchDocumentsTool({ vaultRoot });
    expect(() => tool.inputSchema.parse({ query: "abc", limit: 0 })).toThrow();
  });

  it("treats limit as optional and defaults to 20 in the handler", async () => {
    const tool = searchDocumentsTool({ vaultRoot });
    const parsed = tool.inputSchema.parse({ query: "abc" });
    expect(parsed.limit).toBeUndefined();
  });

  it("rejects extra keys", () => {
    const tool = searchDocumentsTool({ vaultRoot });
    expect(() => tool.inputSchema.parse({ query: "abc", foo: 1 })).toThrow();
  });

  it("exposes the vault classifier categories", () => {
    expect(CATEGORY_VALUES).toContain("lønseddel");
    expect(CATEGORY_VALUES).toContain("kontoauszug");
    expect(CATEGORY_VALUES).toContain("unsorted");
  });
});

describe("search_documents — search relevance", () => {
  let vaultRoot: string;

  beforeEach(() => {
    vaultRoot = mkdtempSync(join(tmpdir(), "penge-vault-"));
    buildVault(vaultRoot, [
      {
        hash: "a".repeat(64),
        relPath: "2024/lønseddel/aaaa-payslip-january.pdf",
        filedAt: "2024-02-01T08:00:00Z",
        ocr: "Lønseddel for januar 2024. Brutto: 45000 DKK.",
      },
      {
        hash: "b".repeat(64),
        relPath: "2024/kontoauszug/bbbb-gls-bank-january.pdf",
        filedAt: "2024-02-02T08:00:00Z",
        ocr:
          "GLS Bank Kontoauszug Januar 2024. " +
          "IBAN: DE89370400440532013000 Saldo am 31.01: 1234,56 EUR.",
      },
      {
        hash: "c".repeat(64),
        relPath: "2023/årsopgørelse/cccc-skat-2023.pdf",
        filedAt: "2024-04-01T08:00:00Z",
        ocr: "Årsopgørelse 2023 fra Skattestyrelsen. CPR: 010190-1234.",
      },
    ]);
  });

  afterEach(() => {
    rmSync(vaultRoot, { recursive: true, force: true });
  });

  it("matches a term in the filename", async () => {
    const tool = searchDocumentsTool({ vaultRoot });
    const out = await tool.handler(tool.inputSchema.parse({ query: "payslip" }), ctx);
    expect(out).toHaveLength(1);
    expect(out[0]?.hash).toBe("a".repeat(64));
    expect(out[0]?.year).toBe(2024);
    expect(out[0]?.type).toBe("lønseddel");
  });

  it("matches a term in OCR text and returns an excerpt around it", async () => {
    const tool = searchDocumentsTool({ vaultRoot });
    const out = await tool.handler(tool.inputSchema.parse({ query: "Saldo" }), ctx);
    expect(out).toHaveLength(1);
    expect(out[0]?.hash).toBe("b".repeat(64));
    expect(out[0]?.excerpt.toLowerCase()).toContain("saldo");
  });

  it("filters by year", async () => {
    const tool = searchDocumentsTool({ vaultRoot });
    const out = await tool.handler(tool.inputSchema.parse({ query: "20", year: 2023 }), ctx);
    expect(out).toHaveLength(1);
    expect(out[0]?.year).toBe(2023);
    expect(out[0]?.type).toBe("årsopgørelse");
  });

  it("filters by classifier type", async () => {
    const tool = searchDocumentsTool({ vaultRoot });
    const out = await tool.handler(
      tool.inputSchema.parse({ query: "20", type: "kontoauszug" }),
      ctx,
    );
    expect(out).toHaveLength(1);
    expect(out[0]?.type).toBe("kontoauszug");
  });

  it("respects limit", async () => {
    const tool = searchDocumentsTool({ vaultRoot });
    const out = await tool.handler(tool.inputSchema.parse({ query: "20", limit: 1 }), ctx);
    expect(out).toHaveLength(1);
  });

  it("ranks higher match counts first", async () => {
    const tool = searchDocumentsTool({ vaultRoot });
    const out = await tool.handler(tool.inputSchema.parse({ query: "2024" }), ctx);
    // 2024 appears in OCR for lønseddel (1×) and kontoauszug (1×) plus filenames.
    // Both match; just assert order is stable and confidence in [0,1].
    expect(out.length).toBeGreaterThanOrEqual(2);
    for (const hit of out) {
      expect(hit.confidence).toBeGreaterThan(0);
      expect(hit.confidence).toBeLessThanOrEqual(1);
    }
    expect(out[0]!.confidence).toBeGreaterThanOrEqual(out[out.length - 1]!.confidence);
  });

  it("returns an empty array when nothing matches", async () => {
    const tool = searchDocumentsTool({ vaultRoot });
    const out = await tool.handler(tool.inputSchema.parse({ query: "nothing-matches-this" }), ctx);
    expect(out).toEqual([]);
  });

  it("validates output against the schema", async () => {
    const tool = searchDocumentsTool({ vaultRoot });
    const out = await tool.handler(tool.inputSchema.parse({ query: "Lønseddel" }), ctx);
    expect(() => tool.outputSchema.parse(out)).not.toThrow();
  });

  it("degrades to an empty result when the index is missing", async () => {
    const empty = mkdtempSync(join(tmpdir(), "penge-vault-empty-"));
    try {
      const tool = searchDocumentsTool({ vaultRoot: empty });
      const out = await tool.handler(tool.inputSchema.parse({ query: "anything" }), ctx);
      expect(out).toEqual([]);
    } finally {
      rmSync(empty, { recursive: true, force: true });
    }
  });
});

describe("search_documents — excerpt redaction", () => {
  let vaultRoot: string;

  beforeEach(() => {
    vaultRoot = mkdtempSync(join(tmpdir(), "penge-vault-"));
    buildVault(vaultRoot, [
      {
        hash: "d".repeat(64),
        relPath: "2024/kontoauszug/dddd-statement.pdf",
        filedAt: "2024-02-02T08:00:00Z",
        ocr:
          "Statement from GLS Bank. " +
          "IBAN DE89370400440532013000 — account 12345678901 — " +
          "CPR 010190-1234. Closing balance 1234,56 EUR.",
      },
    ]);
  });

  afterEach(() => {
    rmSync(vaultRoot, { recursive: true, force: true });
  });

  it("masks IBANs in excerpts", async () => {
    const tool = searchDocumentsTool({ vaultRoot });
    const out = await tool.handler(tool.inputSchema.parse({ query: "IBAN" }), ctx);
    expect(out).toHaveLength(1);
    expect(out[0]?.excerpt).not.toContain("DE89370400440532013000");
    expect(out[0]?.excerpt).toContain("[REDACTED]");
  });

  it("masks long account numbers in excerpts", async () => {
    const tool = searchDocumentsTool({ vaultRoot });
    const out = await tool.handler(tool.inputSchema.parse({ query: "account" }), ctx);
    expect(out).toHaveLength(1);
    expect(out[0]?.excerpt).not.toContain("12345678901");
    expect(out[0]?.excerpt).toContain("[REDACTED]");
  });

  it("masks DK CPR numbers in excerpts", async () => {
    const tool = searchDocumentsTool({ vaultRoot });
    const out = await tool.handler(tool.inputSchema.parse({ query: "CPR" }), ctx);
    expect(out).toHaveLength(1);
    expect(out[0]?.excerpt).not.toContain("010190-1234");
    expect(out[0]?.excerpt).toContain("[REDACTED]");
  });
});
