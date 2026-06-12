import { describe, expect, it } from "vitest";

import {
  normalizeCounterparty,
  suggestForRow,
  suggestImportMappingTool,
  type ImportMappingQueryRunner,
} from "../src/tools/suggestImportMapping.js";

interface CapturedCall {
  sql: string;
  params: ReadonlyArray<unknown>;
}

/** Runner that answers the session query first, then the rows query. */
function makeRunner(
  sessionRows: Record<string, unknown>[],
  importRows: Record<string, unknown>[],
): ImportMappingQueryRunner & { calls: CapturedCall[] } {
  const calls: CapturedCall[] = [];
  return {
    calls,
    async query(sql, params) {
      calls.push({ sql, params });
      const rows = calls.length === 1 ? sessionRows : importRows;
      return { rows: rows as never };
    },
  };
}

const ctx = { serverName: "test", serverVersion: "0.0.0-test" };

const SESSION_ID = "a31d8f7e-1111-4222-8333-444455556666";

const stagedSession = {
  id: SESSION_ID,
  source: "nordnet_transactions",
  status: "staged",
};

function txnRow(payload: Record<string, unknown>, index = 0): Record<string, unknown> {
  return {
    id: `row-${String(index)}`,
    row_index: index,
    kind: "transaction",
    payload,
  };
}

describe("suggest_import_mapping — schema validation", () => {
  it("accepts a well-formed payload", () => {
    const tool = suggestImportMappingTool({ runner: makeRunner([], []) });
    expect(() => tool.inputSchema.parse({ import_session_id: SESSION_ID })).not.toThrow();
    expect(() =>
      tool.inputSchema.parse({ import_session_id: SESSION_ID, limit: 50 }),
    ).not.toThrow();
  });

  it("rejects non-UUID session ids", () => {
    const tool = suggestImportMappingTool({ runner: makeRunner([], []) });
    expect(() => tool.inputSchema.parse({ import_session_id: "not-a-uuid" })).toThrow();
  });

  it("rejects out-of-range limits and unknown keys", () => {
    const tool = suggestImportMappingTool({ runner: makeRunner([], []) });
    expect(() => tool.inputSchema.parse({ import_session_id: SESSION_ID, limit: 0 })).toThrow();
    expect(() =>
      tool.inputSchema.parse({ import_session_id: SESSION_ID, limit: 10_001 }),
    ).toThrow();
    expect(() => tool.inputSchema.parse({ import_session_id: SESSION_ID, extra: 1 })).toThrow();
  });

  it("rejects malformed table identifiers at construction time", () => {
    expect(() =>
      suggestImportMappingTool({
        runner: makeRunner([], []),
        sessionTable: "import_session; DROP TABLE x",
      }),
    ).toThrow(/sessionTable/);
    expect(() =>
      suggestImportMappingTool({ runner: makeRunner([], []), rowTable: "no_schema" }),
    ).toThrow(/rowTable/);
  });
});

describe("suggest_import_mapping — session guards", () => {
  it("fails when the session does not exist", async () => {
    const tool = suggestImportMappingTool({ runner: makeRunner([], []) });
    await expect(tool.handler({ import_session_id: SESSION_ID }, ctx)).rejects.toThrow(/not found/);
  });

  it("fails when the session is not staged", async () => {
    const runner = makeRunner([{ ...stagedSession, status: "committed" }], []);
    const tool = suggestImportMappingTool({ runner });
    await expect(tool.handler({ import_session_id: SESSION_ID }, ctx)).rejects.toThrow(
      /'committed', not 'staged'/,
    );
  });

  it("skips excluded rows in SQL and parameterizes session id and limit", async () => {
    const runner = makeRunner([stagedSession], []);
    const tool = suggestImportMappingTool({ runner });
    await tool.handler({ import_session_id: SESSION_ID, limit: 25 }, ctx);
    expect(runner.calls).toHaveLength(2);
    expect(runner.calls[0]!.params).toEqual([SESSION_ID]);
    expect(runner.calls[1]!.sql).toMatch(/excluded = FALSE/);
    expect(runner.calls[1]!.params).toEqual([SESSION_ID, 25]);
  });
});

describe("suggestForRow — category rules", () => {
  it("maps canonical nordnet kinds with high confidence", () => {
    const row = {
      id: "r1",
      row_index: 0,
      kind: "transaction",
      payload: { canonical_kind: "dividend", instrument_name: "iShares Core MSCI World" },
    };
    const suggestions = suggestForRow("nordnet_transactions", row);
    const category = suggestions.find((s) => s.field === "category");
    expect(category).toMatchObject({
      value: "investment.income.dividend",
      confidence: 0.9,
    });
    expect(category!.reason).toMatch(/canonical/);
  });

  it("maps growney kinds from the `kind` payload field", () => {
    const row = {
      id: "r1",
      row_index: 0,
      kind: "transaction",
      payload: { kind: "fee", description: "Verwaltungsgebühr" },
    };
    const category = suggestForRow("growney", row).find((s) => s.field === "category");
    expect(category).toMatchObject({ value: "cost.fee", confidence: 0.9 });
  });

  it("falls back to keyword matching on free text with lower confidence", () => {
    const row = {
      id: "r1",
      row_index: 0,
      kind: "transaction",
      payload: { canonical_kind: "unknown", text: "Depotgebyr 4. kvartal" },
    };
    const category = suggestForRow("nordnet_transactions", row).find((s) => s.field === "category");
    expect(category).toMatchObject({ value: "cost.fee" });
    expect(category!.confidence).toBeLessThan(0.9);
  });

  it("emits no category for non-transaction rows", () => {
    const row = { id: "r1", row_index: 0, kind: "holding", payload: { name: "Some Fund" } };
    const categories = suggestForRow("growney", row).filter((s) => s.field === "category");
    expect(categories).toHaveLength(0);
  });
});

describe("suggestForRow — counterparty normalization", () => {
  it("collapses whitespace in instrument names", () => {
    const row = txnRow({
      canonical_kind: "buy",
      instrument_name: "  iShares   Core MSCI World\tUCITS ETF ",
    });
    const counterparty = suggestForRow("nordnet_transactions", row as never).find(
      (s) => s.field === "counterparty",
    );
    expect(counterparty).toMatchObject({
      value: "iShares Core MSCI World UCITS ETF",
      confidence: 0.7,
    });
  });

  it("redacts account numbers from free text and skips redaction-only values", () => {
    const withText = txnRow({
      canonical_kind: "internal_transfer",
      text: "Internal from 60109543",
    });
    const counterparty = suggestForRow("nordnet_transactions", withText as never).find(
      (s) => s.field === "counterparty",
    );
    expect(counterparty!.value).not.toMatch(/60109543/);
    expect(counterparty!.value).toContain("[REDACTED]");

    const onlyDigits = txnRow({ canonical_kind: "deposit", text: "12345678" });
    const none = suggestForRow("nordnet_transactions", onlyDigits as never).filter(
      (s) => s.field === "counterparty",
    );
    expect(none).toHaveLength(0);
  });

  it("normalizeCounterparty is idempotent", () => {
    const once = normalizeCounterparty("Fonds  ABC 99887766");
    expect(normalizeCounterparty(once)).toBe(once);
  });
});

describe("suggestForRow — asset-class rules", () => {
  it("classifies manual balances as cash and pfa schemes as pension", () => {
    const balance = { id: "r1", row_index: 0, kind: "balance", payload: { entity: "A" } };
    expect(
      suggestForRow("manual_balances", balance).find((s) => s.field === "asset_class"),
    ).toMatchObject({ value: "cash", confidence: 0.95 });

    const scheme = { id: "r2", row_index: 1, kind: "scheme", payload: { scheme_kind: "livrente" } };
    expect(suggestForRow("pfa", scheme).find((s) => s.field === "asset_class")).toMatchObject({
      value: "pension",
      confidence: 0.95,
    });
  });

  it("keyword-matches instrument names, preferring specific over generic rules", () => {
    const bond = {
      id: "r1",
      row_index: 0,
      kind: "holding",
      payload: { name: "Xtrackers Global Government Bond UCITS ETF" },
    };
    expect(suggestForRow("growney", bond).find((s) => s.field === "asset_class")).toMatchObject({
      value: "bond_fund",
    });

    const equity = {
      id: "r2",
      row_index: 1,
      kind: "holding",
      payload: { name: "Vanguard FTSE All-World UCITS ETF" },
    };
    expect(suggestForRow("growney", equity).find((s) => s.field === "asset_class")).toMatchObject({
      value: "equity_etf",
    });

    const unknown = {
      id: "r3",
      row_index: 2,
      kind: "holding",
      payload: { name: "Mystery Holding" },
    };
    expect(suggestForRow("growney", unknown).filter((s) => s.field === "asset_class")).toHaveLength(
      0,
    );
  });
});

describe("suggest_import_mapping — end to end", () => {
  it("returns validated suggestions for a staged nordnet session", async () => {
    const runner = makeRunner(
      [stagedSession],
      [
        txnRow(
          {
            canonical_kind: "buy",
            instrument_name: "iShares Core MSCI World UCITS ETF",
            text: "KØBT 10 stk",
          },
          0,
        ),
        txnRow({ canonical_kind: "internal_transfer", text: "Internal from 60109543" }, 1),
      ],
    );
    const tool = suggestImportMappingTool({ runner });
    const output = await tool.handler({ import_session_id: SESSION_ID }, ctx);
    expect(() => tool.outputSchema.parse(output)).not.toThrow();

    expect(output.session).toEqual({
      id: SESSION_ID,
      source: "nordnet_transactions",
      status: "staged",
      rows_considered: 2,
    });
    const fields = output.suggestions.map((s) => s.field);
    expect(fields).toContain("category");
    expect(fields).toContain("counterparty");
    expect(fields).toContain("asset_class");
    for (const suggestion of output.suggestions) {
      expect(suggestion.value).not.toMatch(/\d{8,}/);
      expect(suggestion.reason).not.toMatch(/\d{8,}/);
    }
  });

  it("is deterministic: identical inputs yield identical output", async () => {
    const rows = [txnRow({ canonical_kind: "dividend", instrument_name: "Fund A" }, 0)];
    const toolA = suggestImportMappingTool({ runner: makeRunner([stagedSession], rows) });
    const toolB = suggestImportMappingTool({ runner: makeRunner([stagedSession], rows) });
    const a = await toolA.handler({ import_session_id: SESSION_ID }, ctx);
    const b = await toolB.handler({ import_session_id: SESSION_ID }, ctx);
    expect(a).toEqual(b);
  });

  it("tolerates malformed payloads without throwing", async () => {
    const runner = makeRunner(
      [stagedSession],
      [
        { id: "r0", row_index: 0, kind: "transaction", payload: null },
        { id: "r1", row_index: 1, kind: "transaction", payload: ["not", "an", "object"] },
      ],
    );
    const tool = suggestImportMappingTool({ runner });
    const output = await tool.handler({ import_session_id: SESSION_ID }, ctx);
    expect(output.session.rows_considered).toBe(2);
    expect(output.suggestions).toHaveLength(0);
  });
});
