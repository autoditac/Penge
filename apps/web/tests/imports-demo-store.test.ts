import { beforeEach, describe, expect, it } from "vitest";

import {
  demoCommitImport,
  demoDiscardImport,
  demoGetImport,
  demoListImports,
  demoPatchImportRow,
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
