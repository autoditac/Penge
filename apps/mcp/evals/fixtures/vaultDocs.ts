/**
 * Synthetic vault layout for the `search_documents` goldens.
 *
 * All content is fabricated. Account numbers below are deliberately
 * malformed but match the *shape* the redactor must mask (DK CPR,
 * IBAN, long digit runs) so the goldens can prove that excerpts never
 * leak raw values.
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
    // Contains a fake CPR-shaped value the redactor must mask.
    ocr: "Lønseddel januar 2024. Brutto 45000 DKK. CPR: 010190-1234.",
  },
  {
    hash: "b".repeat(64),
    relPath: "2024/kontoauszug/bbbb-gls-bank-january.pdf",
    filedAt: "2024-02-02T08:00:00Z",
    // Contains a fake IBAN the redactor must mask.
    ocr: "GLS Bank Kontoauszug Januar 2024. IBAN: DE89370400440532013000 Saldo 1234,56 EUR.",
  },
  {
    hash: "c".repeat(64),
    relPath: "2023/årsopgørelse/cccc-skat-2023.pdf",
    filedAt: "2024-04-01T08:00:00Z",
    ocr: "Årsopgørelse 2023 fra Skattestyrelsen. Sagsnr 99887766554433.",
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
