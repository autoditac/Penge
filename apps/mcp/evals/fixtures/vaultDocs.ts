/**
 * Synthetic vault layout for the `search_documents` goldens.
 *
 * All content is fabricated and uses placeholders that match the
 * *shape* the redactor must mask (DK CPR, IBAN, long digit runs) but
 * are clearly invalid: the IBAN has all-zero account/check digits, the
 * "CPR" carries an impossible birthdate (00-00-00) and a zero serial,
 * and the case number is a flat run of nines. None of these can be
 * mistaken for real PII or pass a checksum-aware secret scanner — the
 * goldens still prove that excerpts never leak the raw values.
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export interface FixtureDoc {
  hash: string;
  relPath: string;
  filedAt: string;
  ocr: string;
}

export const SYNTHETIC_VAULT_DOCS: FixtureDoc[] = [
  {
    hash: "a".repeat(64),
    relPath: "2024/lønseddel/aaaa-payslip-january.pdf",
    filedAt: "2024-02-01T08:00:00Z",
    // Impossible CPR: birthdate 00-00-00 and serial 0000.
    ocr: "Lønseddel januar 2024. Brutto 45000 DKK. CPR: 000000-0000.",
  },
  {
    hash: "b".repeat(64),
    relPath: "2024/kontoauszug/bbbb-gls-bank-january.pdf",
    filedAt: "2024-02-02T08:00:00Z",
    // Invalid IBAN: country DE, all-zero check + BBAN. Right shape, wrong checksum.
    ocr: "GLS Bank Kontoauszug Januar 2024. IBAN: DE00000000000000000000 Saldo 1234,56 EUR.",
  },
  {
    hash: "c".repeat(64),
    relPath: "2023/årsopgørelse/cccc-skat-2023.pdf",
    filedAt: "2024-04-01T08:00:00Z",
    // Long digit run (placeholder Sagsnr) that the redactor must mask.
    ocr: "Årsopgørelse 2023 fra Skattestyrelsen. Sagsnr 99999999999999.",
  },
  {
    hash: "d".repeat(64),
    relPath: "2024/depotauszug/dddd-nordnet-january.pdf",
    filedAt: "2024-02-15T08:00:00Z",
    ocr: "Nordnet Depotauszug. Position ETF 100 stk @ 100 DKK.",
  },
];

interface IndexEntry {
  path: string;
  size: number;
  filed_at: string;
}

export function buildVault(root: string, docs: readonly FixtureDoc[]): void {
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
