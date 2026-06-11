/** Pure presentation/transform helpers for the import wizard (tested). */

import type { ImportRow, RowIssue } from "../api/schemas";

export const SOURCE_LABELS: Readonly<Record<string, string>> = {
  nordnet_transactions: "Nordnet transactions (CSV)",
  growney: "Growney Depotauszug (PDF)",
  pfa: "PFA Pensionsoversigt (PDF)",
  manual_balances: "Manual balances (JSON)",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

export type BadgeTone = "good" | "watch" | "critical" | "info";

export type RowBadge = {
  readonly label: string;
  readonly tone: BadgeTone;
};

/** Visual badge for one staged row; exclusion wins over status. */
export function rowBadge(row: Pick<ImportRow, "status" | "excluded">): RowBadge {
  if (row.excluded) {
    return { label: "excluded", tone: "info" };
  }
  switch (row.status) {
    case "ok":
      return { label: "ok", tone: "good" };
    case "warning":
      return { label: "duplicate", tone: "watch" };
    case "error":
      return { label: "error", tone: "critical" };
    default:
      return { label: row.status, tone: "info" };
  }
}

export function summarizeIssues(issues: readonly RowIssue[]): string {
  return issues.map((issue) => issue.detail).join("; ");
}

export type EditableField = {
  readonly key: string;
  readonly value: string;
};

function isScalar(value: unknown): value is string | number | boolean | null {
  return (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  );
}

/** Flat scalar payload fields as editable strings, preserving key order. */
export function editableFields(payload: Readonly<Record<string, unknown>>): EditableField[] {
  return Object.entries(payload)
    .filter((entry): entry is [string, string | number | boolean | null] => isScalar(entry[1]))
    .map(([key, value]) => ({ key, value: value === null ? "" : String(value) }));
}

/** Merge edited string values back over the original payload.
 *
 * Empty strings become `null` (the wire encoding for "unset"); non-scalar
 * fields (nested objects/arrays) are passed through untouched.
 */
export function applyEdits(
  payload: Readonly<Record<string, unknown>>,
  edits: Readonly<Record<string, string>>,
): Record<string, unknown> {
  const next: Record<string, unknown> = { ...payload };
  for (const [key, value] of Object.entries(edits)) {
    next[key] = value === "" ? null : value;
  }
  return next;
}

/** A session page is committable when every included row is non-error.
 *
 * The server enforces this independently; the client check only drives
 * the button state for the rows it can see.
 */
export function canCommit(rows: readonly Pick<ImportRow, "status" | "excluded">[]): boolean {
  return rows.length > 0 && rows.every((row) => row.excluded || row.status !== "error");
}

export function shortSha(sha256: string): string {
  return sha256.slice(0, 12);
}

export function formatTimestamp(isoTimestamp: string): string {
  const parsed = new Date(isoTimestamp);
  if (Number.isNaN(parsed.getTime())) {
    return isoTimestamp;
  }
  return parsed.toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
