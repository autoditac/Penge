/**
 * Value-pattern redaction for free-text excerpts (e.g. from OCR sidecars).
 *
 * The audit logger (`audit.ts`) redacts by *key name* on structured
 * objects. That is the right policy for tool arguments but not for
 * raw text we surface back through MCP. This module redacts by
 * *value pattern* so account numbers, IBANs and DK CPR numbers that
 * happen to land in an excerpt are masked before leaving the process.
 */

const REDACTED = "[REDACTED]";

const PATTERNS: RegExp[] = [
  // IBAN. Two shapes covered:
  //   1. Contiguous: country (2) + check (2) + 11–30 alphanumerics.
  //   2. Printed groups: country/check then `(space|dash)+ 4 chars`
  //      repeated 2–7 times plus a final 1–4 char group, mirroring the
  //      standard 4-char IBAN grouping that survives OCR most often.
  // Case-insensitive (`/i`) so lowercase OCR variants are caught.
  // Carefully bounded so we cannot eat surrounding words like "Saldo".
  /\b[A-Z]{2}\d{2}(?:[A-Z0-9]{11,30}|(?:[ -][A-Z0-9]{4}){2,7}[ -][A-Z0-9]{1,4})\b/gi,
  // DK CPR: 6 digits, optional dash, 4 digits.
  /\b\d{6}-?\d{4}\b/g,
  // Long digit runs typical of account/customer numbers.
  /\b\d{8,}\b/g,
];

/**
 * Replace IBANs, CPR numbers and long digit runs in `text` with
 * `[REDACTED]`. Idempotent: applying twice yields the same string.
 */
export function redactText(text: string): string {
  let out = text;
  for (const pattern of PATTERNS) {
    out = out.replace(pattern, REDACTED);
  }
  return out;
}
