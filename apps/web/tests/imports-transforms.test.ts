import { describe, expect, it } from "vitest";

import {
  applyEdits,
  canCommit,
  editableFields,
  formatTimestamp,
  rowBadge,
  shortSha,
  sourceLabel,
  summarizeIssues,
} from "../src/imports/transforms";

describe("sourceLabel", () => {
  it("maps known sources to human labels", () => {
    expect(sourceLabel("nordnet_transactions")).toContain("Nordnet");
    expect(sourceLabel("growney")).toContain("Growney");
    expect(sourceLabel("pfa")).toContain("PFA");
    expect(sourceLabel("manual_balances")).toContain("Manual");
  });

  it("falls back to the raw source id", () => {
    expect(sourceLabel("unknown_source")).toBe("unknown_source");
  });
});

describe("rowBadge", () => {
  it("maps statuses to tones", () => {
    expect(rowBadge({ status: "ok", excluded: false })).toEqual({ label: "ok", tone: "good" });
    expect(rowBadge({ status: "warning", excluded: false })).toEqual({
      label: "duplicate",
      tone: "watch",
    });
    expect(rowBadge({ status: "error", excluded: false })).toEqual({
      label: "error",
      tone: "critical",
    });
  });

  it("lets exclusion win over status", () => {
    expect(rowBadge({ status: "error", excluded: true })).toEqual({
      label: "excluded",
      tone: "info",
    });
  });
});

describe("summarizeIssues", () => {
  it("joins issue details", () => {
    expect(
      summarizeIssues([
        { code: "duplicate", detail: "already imported" },
        { code: "invalid", detail: "bad currency" },
      ]),
    ).toBe("already imported; bad currency");
    expect(summarizeIssues([])).toBe("");
  });
});

describe("editableFields", () => {
  it("extracts scalar fields as strings", () => {
    expect(
      editableFields({
        currency: "EUR",
        balance: "100.00",
        quantity: 4,
        active: true,
        note: null,
      }),
    ).toEqual([
      { key: "currency", value: "EUR" },
      { key: "balance", value: "100.00" },
      { key: "quantity", value: "4" },
      { key: "active", value: "true" },
      { key: "note", value: "" },
    ]);
  });

  it("skips nested objects and arrays", () => {
    expect(editableFields({ nested: { a: 1 }, list: [1, 2], name: "x" })).toEqual([
      { key: "name", value: "x" },
    ]);
  });
});

describe("applyEdits", () => {
  it("overlays edits and maps empty strings to null", () => {
    const payload = { currency: "XXX", balance: "1.00", nested: { keep: true } };
    expect(applyEdits(payload, { currency: "EUR", balance: "" })).toEqual({
      currency: "EUR",
      balance: null,
      nested: { keep: true },
    });
  });

  it("does not mutate the original payload", () => {
    const payload = { currency: "XXX" };
    applyEdits(payload, { currency: "EUR" });
    expect(payload.currency).toBe("XXX");
  });
});

describe("canCommit", () => {
  it("requires at least one row", () => {
    expect(canCommit([])).toBe(false);
  });

  it("accepts ok and warning rows", () => {
    expect(
      canCommit([
        { status: "ok", excluded: false },
        { status: "warning", excluded: false },
      ]),
    ).toBe(true);
  });

  it("rejects included error rows but accepts excluded ones", () => {
    expect(
      canCommit([
        { status: "ok", excluded: false },
        { status: "error", excluded: false },
      ]),
    ).toBe(false);
    expect(
      canCommit([
        { status: "ok", excluded: false },
        { status: "error", excluded: true },
      ]),
    ).toBe(true);
  });
});

describe("shortSha", () => {
  it("truncates to twelve characters", () => {
    expect(shortSha("abcdef0123456789deadbeef")).toBe("abcdef012345");
  });
});

describe("formatTimestamp", () => {
  it("renders a localized timestamp", () => {
    expect(formatTimestamp("2026-06-01T09:00:00Z")).toMatch(/2026/);
  });

  it("falls back to the raw string when unparsable", () => {
    expect(formatTimestamp("not-a-date")).toBe("not-a-date");
  });
});
