/** Money helpers for the Decimal-as-JSON-string wire contract (ADR-0035).
 *
 * The read API serialises Decimal columns as strings ("1234.5600") so no
 * precision is lost in transit. The UI converts to `number` only at the edge,
 * for charting and display — never for arithmetic that feeds back into data.
 */

export type Currency = "EUR" | "DKK";

/** Parse a decimal wire string to a float for display/charting. */
export function parseDecimal(value: string | null): number | null {
  if (value === null || value.trim() === "") {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

const moneyFormats: Record<Currency, Intl.NumberFormat> = {
  EUR: new Intl.NumberFormat("en-DK", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }),
  DKK: new Intl.NumberFormat("en-DK", {
    style: "currency",
    currency: "DKK",
    maximumFractionDigits: 0,
  }),
};

/** Format a numeric amount with its currency symbol, no fraction digits. */
export function formatMoney(value: number | null, currency: Currency): string {
  if (value === null) {
    return "—";
  }
  return moneyFormats[currency].format(value);
}

/** Compact axis-label form, e.g. 1234567 → "1.2M". */
export function formatCompact(value: number): string {
  return new Intl.NumberFormat("en-DK", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

/** Format a 0..1 share as a percentage with one decimal. */
export function formatShare(value: number | null): string {
  if (value === null) {
    return "—";
  }
  return new Intl.NumberFormat("en-DK", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

/** ISO date (YYYY-MM-DD) for query parameters. */
export function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** ISO date `days` ago, relative to `today` (defaults to now). */
export function isoDaysAgo(days: number, today: Date = new Date()): string {
  const past = new Date(today.getTime() - days * 24 * 60 * 60 * 1000);
  return isoDate(past);
}
