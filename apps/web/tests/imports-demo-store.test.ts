import { beforeEach, describe, expect, it } from "vitest";

import {
  demoCommitImport,
  demoDiscardImport,
  demoGetImport,
  demoListImports,
  demoPatchImportRow,
  demoSuggestImports,
  demoResetImports,
  demoUploadImport,
} from "../src/demo/importsStore";

function fakeFile(name: string): File {
  return new File(["synthetic"], name);
}

beforeEach(() => {
  demoResetImports();
});

describe("demo imports store", () => {
  it("stages deterministic rows on upload", () => {
    const session = demoUploadImport(fakeFile("transactions.csv"));
    expect(session.source).toBe("nordnet_transactions");
    expect(session.status).toBe("staged");
    expect(session.rows).toHaveLength(2);
    expect(session.row_counts).toEqual({ total: 2, ok: 1, warning: 1, error: 0, excluded: 0 });
  });

  it("detects manual balances from the filename and stages an error row", () => {
    const session = demoUploadImport(fakeFile("balances.json"));
    expect(session.source).toBe("manual_balances");
    expect(session.row_counts.error).toBe(1);
  });

  it("supports the full fix-then-commit flow", () => {
    const session = demoUploadImport(fakeFile("balances.json"));
    const errorRow = session.rows.find((row) => row.status === "error");
    if (errorRow === undefined) {
      throw new Error("expected a staged error row");
    }

    expect(() => demoCommitImport(session.id)).toThrow(/error rows/);

    const fixed = demoPatchImportRow(session.id, errorRow.id, {
      payload: { ...errorRow.payload, currency: "DKK" },
    });
    expect(fixed.status).toBe("ok");
    expect(fixed.edited).toBe(true);

    const response = demoCommitImport(session.id);
    expect(response.session.status).toBe("committed");
    expect(response.counts.holding_snapshots).toBe(2);
    expect(demoGetImport(session.id).status).toBe("committed");
  });

  it("skips excluded rows at commit", () => {
    const session = demoUploadImport(fakeFile("balances.json"));
    const errorRow = session.rows.find((row) => row.status === "error");
    if (errorRow === undefined) {
      throw new Error("expected a staged error row");
    }
    demoPatchImportRow(session.id, errorRow.id, { excluded: true });
    const response = demoCommitImport(session.id);
    expect(response.counts.holding_snapshots).toBe(1);
  });

  it("discards staged sessions but protects committed ones", () => {
    const staged = demoUploadImport(fakeFile("a.csv"));
    expect(demoDiscardImport(staged.id).status).toBe("discarded");

    const committed = demoUploadImport(fakeFile("b.csv"));
    demoCommitImport(committed.id);
    expect(() => demoDiscardImport(committed.id)).toThrow(/audit/);
  });

  it("lists sessions newest first", () => {
    const first = demoUploadImport(fakeFile("a.csv"));
    const second = demoUploadImport(fakeFile("b.csv"));
    const listed = demoListImports();
    expect(listed.total).toBe(2);
    expect(listed.sessions.map((session) => session.id)).toEqual([second.id, first.id]);
  });
});

describe("demo mapping suggestions (#210)", () => {
  it("suggests canonical categories for known transaction kinds", () => {
    const session = demoUploadImport(fakeFile("transactions.csv"));
    const response = demoSuggestImports(session.id);
    expect(response.suggested_by).toBe("suggest_import_mapping");
    expect(response.session.id).toBe(session.id);
    expect(response.session.rows_considered).toBe(2);
    const fields = response.suggestions.map((s) => `${s.field}=${s.value}`);
    expect(fields).toContain("category=deposit");
    expect(fields).toContain("category=buy");
  });

  it("suggests cash asset class for balance rows and skips excluded rows", () => {
    const session = demoUploadImport(fakeFile("balances.json"));
    const firstRow = session.rows[0];
    if (firstRow === undefined) {
      throw new Error("expected staged rows");
    }
    demoPatchImportRow(session.id, firstRow.id, { excluded: true });
    const response = demoSuggestImports(session.id);
    expect(response.session.rows_considered).toBe(1);
    expect(response.suggestions.every((s) => s.row_id !== firstRow.id)).toBe(true);
    expect(response.suggestions.every((s) => s.field === "asset_class")).toBe(true);
  });

  it("rejects suggestions for non-staged sessions", () => {
    const session = demoUploadImport(fakeFile("transactions.csv"));
    demoCommitImport(session.id);
    expect(() => demoSuggestImports(session.id)).toThrow(/only staged sessions/);
  });

  it("applies accepted mappings with AI provenance via patch", () => {
    const session = demoUploadImport(fakeFile("transactions.csv"));
    const row = session.rows[0];
    if (row === undefined) {
      throw new Error("expected staged rows");
    }
    const accepted = demoPatchImportRow(session.id, row.id, {
      mappings: { category: "deposit" },
      suggestedBy: "suggest_import_mapping",
    });
    expect(accepted.mappings).toEqual({ category: "deposit" });
    expect(accepted.suggested_by).toBe("suggest_import_mapping");
    expect(accepted.accepted_at).not.toBeNull();

    const manual = demoPatchImportRow(session.id, row.id, {
      mappings: { category: "household" },
    });
    expect(manual.suggested_by).toBeNull();
    expect(manual.accepted_at).toBeNull();
  });
});
