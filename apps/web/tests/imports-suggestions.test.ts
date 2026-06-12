/** Unit tests for the suggestion helpers (issue #210). */

import { describe, expect, it } from "vitest";

import type { MappingSuggestion } from "../src/api/schemas";
import {
  confidenceLabel,
  filterAtOrAboveConfidence,
  groupSuggestionsByRow,
  mergeMappings,
  pendingSuggestions,
} from "../src/imports/suggestions";

function suggestion(overrides: Partial<MappingSuggestion>): MappingSuggestion {
  return {
    confidence: 0.9,
    field: "category",
    kind: "transaction",
    reason: "canonical transaction kind",
    row_id: "row-1",
    row_index: 0,
    value: "deposit",
    ...overrides,
  };
}

describe("groupSuggestionsByRow", () => {
  it("groups by row id preserving order", () => {
    const grouped = groupSuggestionsByRow([
      suggestion({ row_id: "row-1", field: "category" }),
      suggestion({ row_id: "row-2", field: "asset_class", value: "cash" }),
      suggestion({ row_id: "row-1", field: "counterparty", value: "Employer" }),
    ]);
    expect([...grouped.keys()]).toEqual(["row-1", "row-2"]);
    expect(grouped.get("row-1")?.map((s) => s.field)).toEqual(["category", "counterparty"]);
    expect(grouped.get("row-2")).toHaveLength(1);
  });

  it("returns an empty map for no suggestions", () => {
    expect(groupSuggestionsByRow([]).size).toBe(0);
  });
});

describe("filterAtOrAboveConfidence", () => {
  it("keeps suggestions at or above the threshold", () => {
    const kept = filterAtOrAboveConfidence(
      [
        suggestion({ confidence: 0.9 }),
        suggestion({ confidence: 0.8 }),
        suggestion({ confidence: 0.79 }),
      ],
      0.8,
    );
    expect(kept.map((s) => s.confidence)).toEqual([0.9, 0.8]);
  });
});

describe("mergeMappings", () => {
  it("merges accepted suggestions over current mappings", () => {
    const merged = mergeMappings({ category: "old", counterparty: "Keep A/S" }, [
      suggestion({ field: "category", value: "deposit" }),
      suggestion({ field: "asset_class", value: "cash" }),
    ]);
    expect(merged).toEqual({
      category: "deposit",
      counterparty: "Keep A/S",
      asset_class: "cash",
    });
  });

  it("lets the last accepted suggestion win per field", () => {
    const merged = mergeMappings({}, [
      suggestion({ field: "category", value: "first" }),
      suggestion({ field: "category", value: "second" }),
    ]);
    expect(merged).toEqual({ category: "second" });
  });

  it("does not mutate the current mappings", () => {
    const current = { category: "old" };
    mergeMappings(current, [suggestion({ field: "category", value: "new" })]);
    expect(current).toEqual({ category: "old" });
  });
});

describe("pendingSuggestions", () => {
  it("drops suggestions whose value is already applied", () => {
    const row = { mappings: { category: "deposit" } };
    const pending = pendingSuggestions(row, [
      suggestion({ field: "category", value: "deposit" }),
      suggestion({ field: "asset_class", value: "cash" }),
    ]);
    expect(pending.map((s) => s.field)).toEqual(["asset_class"]);
  });

  it("keeps suggestions that differ from the applied value", () => {
    const row = { mappings: { category: "other" } };
    const pending = pendingSuggestions(row, [suggestion({ field: "category", value: "deposit" })]);
    expect(pending).toHaveLength(1);
  });
});

describe("confidenceLabel", () => {
  it("renders a rounded percent", () => {
    expect(confidenceLabel(0.9)).toBe("90 %");
    expect(confidenceLabel(0.55)).toBe("55 %");
    expect(confidenceLabel(1)).toBe("100 %");
  });
});
