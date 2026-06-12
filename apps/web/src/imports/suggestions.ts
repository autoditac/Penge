/** Pure helpers for working with MCP mapping suggestions (issue #210).
 *
 * Kept free of React/query concerns so accept/reject and grouping logic
 * is unit-testable and reusable between live and demo modes.
 */

import type { ImportRow, MappingSuggestion } from "../api/schemas";

/** Group a flat suggestion list by row id, preserving response order. */
export function groupSuggestionsByRow(
  suggestions: readonly MappingSuggestion[],
): ReadonlyMap<string, readonly MappingSuggestion[]> {
  const grouped = new Map<string, MappingSuggestion[]>();
  for (const suggestion of suggestions) {
    const bucket = grouped.get(suggestion.row_id);
    if (bucket === undefined) {
      grouped.set(suggestion.row_id, [suggestion]);
    } else {
      bucket.push(suggestion);
    }
  }
  return grouped;
}

/** Suggestions at or above the confidence threshold (bulk accept). */
export function filterAtOrAboveConfidence(
  suggestions: readonly MappingSuggestion[],
  threshold: number,
): readonly MappingSuggestion[] {
  return suggestions.filter((s) => s.confidence >= threshold);
}

/** Merge accepted suggestions into a row's current mappings.
 *
 * Later suggestions for the same field win, mirroring "last accept
 * sticks". Existing mapped fields not covered by the accepted
 * suggestions are preserved.
 */
export function mergeMappings(
  current: Readonly<Record<string, string>>,
  accepted: readonly MappingSuggestion[],
): Record<string, string> {
  const merged: Record<string, string> = { ...current };
  for (const suggestion of accepted) {
    merged[suggestion.field] = suggestion.value;
  }
  return merged;
}

/** Drop suggestions whose value is already applied on the row. */
export function pendingSuggestions(
  row: Pick<ImportRow, "mappings">,
  suggestions: readonly MappingSuggestion[],
): readonly MappingSuggestion[] {
  return suggestions.filter((s) => row.mappings[s.field] !== s.value);
}

/** Format a 0..1 confidence as a percent label, e.g. `90 %`. */
export function confidenceLabel(confidence: number): string {
  return `${Math.round(confidence * 100)} %`;
}
