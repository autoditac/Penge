/**
 * MCP tool: `search_documents`.
 *
 * Searches the on-disk document vault by filename, classifier
 * metadata (year + type derived from the vault path), and OCR
 * sidecar text. Returns ranked references — never raw file
 * contents and never raw account/IBAN/CPR strings; excerpts are
 * redacted with `redactText` before leaving the process.
 *
 * Vault layout (see `src/penge/vault/filer.py`):
 *
 *     <vault_root>/
 *         .index.json                    sha256 -> { path, size, filed_at }
 *         {year}/{type}/{hash}-{slug}.{ext}    classified document
 *         {year}/{type}/{hash}-{slug}.txt      OCR sidecar (UTF-8)
 *
 * The classifier categories are mirrored in `CATEGORY_VALUES` below.
 */

import { existsSync, readFileSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { isAbsolute, join, posix, resolve, sep } from "node:path";

import { z } from "zod";

import { redactText } from "../redact.js";
import type { ToolDefinition } from "../registry.js";

/**
 * Document categories produced by the vault classifier
 * (`src/penge/vault/classifier_rules.yaml`). Plus `unsorted` for
 * documents that did not clear the classifier's `min_confidence`.
 *
 * Keep this list in sync with the YAML — drift is caught by the
 * `unsorted` fallback at runtime, but new categories will only become
 * filterable once added here.
 */
export const CATEGORY_VALUES = [
  "lønseddel",
  "gehaltsabrechnung",
  "årsopgørelse",
  "steuerbescheid",
  "kontoauszug",
  "depotauszug",
  "pfa-statement",
  "hypothek",
  "grundbuch",
  "versicherungspolice",
  "unsorted",
] as const;

const CategoryEnum = z.enum(CATEGORY_VALUES);
export type Category = z.infer<typeof CategoryEnum>;

const InputSchema = z
  .object({
    query: z.string().min(2, "query must be at least 2 characters"),
    year: z.number().int().min(1900).max(9999).optional(),
    type: CategoryEnum.optional(),
    limit: z.number().int().min(1).max(100).optional(),
  })
  .strict();

export type SearchDocumentsInput = z.infer<typeof InputSchema>;

const DEFAULT_LIMIT = 20;

const HitSchema = z
  .object({
    vault_path: z.string(),
    /** Null when the vault path does not start with a 4-digit year folder. */
    year: z.number().int().nullable(),
    type: z.string(),
    classified_at: z.string(),
    hash: z.string(),
    excerpt: z.string(),
    confidence: z.number().min(0).max(1),
  })
  .strict();

const OutputSchema = z.array(HitSchema);
export type SearchDocumentsOutput = z.infer<typeof OutputSchema>;

interface IndexEntry {
  path: string;
  size: number;
  filed_at: string;
}

interface RawIndex {
  [hash: string]: IndexEntry;
}

interface ScoredHit {
  vault_path: string;
  year: number | null;
  type: string;
  classified_at: string;
  hash: string;
  excerpt: string;
  /** Raw match count used for ranking. Mapped to [0, 1] confidence on the way out. */
  matches: number;
}

/**
 * Read and minimally validate the vault index. Returns an empty map
 * if the file is missing or unreadable so the tool degrades to "no
 * results" rather than failing hard.
 */
function readIndex(vaultRoot: string): RawIndex {
  const indexPath = join(vaultRoot, ".index.json");
  if (!existsSync(indexPath)) return {};
  let raw: unknown;
  try {
    // Synchronous because the index is small and read exactly once per
    // call before any per-entry I/O. Per-entry sidecar reads further
    // down are async to keep the event loop responsive.
    raw = JSON.parse(readFileSync(indexPath, "utf-8"));
  } catch {
    return {};
  }
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out: RawIndex = {};
  for (const [hash, entry] of Object.entries(raw as Record<string, unknown>)) {
    if (entry === null || typeof entry !== "object") continue;
    const e = entry as Record<string, unknown>;
    if (typeof e["path"] !== "string") continue;
    if (typeof e["size"] !== "number") continue;
    if (typeof e["filed_at"] !== "string") continue;
    out[hash] = {
      path: e["path"],
      size: e["size"],
      filed_at: e["filed_at"],
    };
  }
  return out;
}

/**
 * Resolve `relPath` (from `.index.json`) to an absolute path **inside**
 * `vaultRoot`. Returns `null` if `relPath` is absolute, contains a
 * `..` segment, or otherwise resolves outside the vault — corrupt or
 * malicious index entries must never cause us to read arbitrary files.
 */
function safeResolveInVault(vaultRoot: string, relPath: string): string | null {
  const normalized = relPath.replace(/\\/g, "/");
  if (normalized === "" || isAbsolute(normalized) || normalized.startsWith("/")) {
    return null;
  }
  if (normalized.split("/").some((segment) => segment === "..")) {
    return null;
  }
  const rootAbs = resolve(vaultRoot);
  const candidate = resolve(rootAbs, normalized);
  if (candidate !== rootAbs && !candidate.startsWith(rootAbs + sep)) {
    return null;
  }
  return candidate;
}

/**
 * Read the OCR sidecar for a vault path (`<hash>-<slug>.<ext>` →
 * `<hash>-<slug>.txt` in the same folder). Returns `""` if missing,
 * unreadable, or if the resolved path would escape `vaultRoot`.
 */
async function readSidecar(vaultRoot: string, relPath: string): Promise<string> {
  const lastDot = relPath.lastIndexOf(".");
  if (lastDot === -1) return "";
  const sidecarRel = `${relPath.slice(0, lastDot)}.txt`;
  const sidecarAbs = safeResolveInVault(vaultRoot, sidecarRel);
  if (sidecarAbs === null) return "";
  try {
    return await readFile(sidecarAbs, "utf-8");
  } catch {
    return "";
  }
}

/**
 * Split `2026/lønseddel/<hash>-<slug>.pdf` into
 * `{ year: 2026, type: "lønseddel" }`. Vault paths are written by
 * `filer.py` using POSIX separators, but `.index.json` could in
 * principle be migrated from Windows — normalize both.
 */
function parseRelPath(relPath: string): { year: number | null; type: string } {
  const normalized = relPath.replace(/\\/g, "/");
  const parts = normalized.split(posix.sep);
  if (parts.length < 3) return { year: null, type: "unsorted" };
  const yearPart = parts[0] ?? "";
  const typePart = parts[1] ?? "unsorted";
  const year = /^\d{4}$/.test(yearPart) ? Number(yearPart) : null;
  return { year, type: typePart };
}

/**
 * Count case-insensitive occurrences of `needle` in `haystack`.
 * Empty `needle` returns 0 so the schema's min-2 guarantee is the
 * single source of truth for query length.
 */
function countOccurrences(haystack: string, needle: string): number {
  if (needle.length === 0) return 0;
  const lcHaystack = haystack.toLowerCase();
  const lcNeedle = needle.toLowerCase();
  let count = 0;
  let idx = lcHaystack.indexOf(lcNeedle);
  while (idx !== -1) {
    count += 1;
    idx = lcHaystack.indexOf(lcNeedle, idx + lcNeedle.length);
  }
  return count;
}

const EXCERPT_RADIUS = 50;

/**
 * Build a ±50-char window around the first case-insensitive match of
 * `needle` in `text`. Returns `""` if `text` is empty or contains no
 * match. The caller is responsible for redaction.
 */
function buildExcerpt(text: string, needle: string): string {
  if (!text || !needle) return "";
  const idx = text.toLowerCase().indexOf(needle.toLowerCase());
  if (idx === -1) return "";
  const start = Math.max(0, idx - EXCERPT_RADIUS);
  const end = Math.min(text.length, idx + needle.length + EXCERPT_RADIUS);
  const prefix = start > 0 ? "…" : "";
  const suffix = end < text.length ? "…" : "";
  // Collapse newlines so the excerpt is one line.
  const window = text.slice(start, end).replace(/\s+/g, " ").trim();
  return `${prefix}${window}${suffix}`;
}

/**
 * Map a raw match count to a [0, 1] confidence using a saturating
 * curve `min(1, n/5)`. Five distinct hits is "very confident"; one
 * hit is 0.2; zero hits is 0 and never reaches the wire because
 * those rows are filtered out before ranking.
 */
function toConfidence(matches: number): number {
  return Math.min(1, matches / 5);
}

export interface SearchDocumentsOptions {
  /**
   * Absolute path to the vault root (where `.index.json` lives).
   * Sourced from `PENGE_VAULT_ROOT` by the entrypoint; injected here
   * so tests can point at a temp directory.
   */
  vaultRoot: string;
}

/**
 * Cap on parallel sidecar reads. Bounded so a vault with thousands of
 * documents cannot exhaust file descriptors or starve other MCP
 * requests sharing the event loop.
 */
const SIDECAR_CONCURRENCY = 8;

async function mapWithConcurrency<T, R>(
  items: readonly T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const out: R[] = new Array<R>(items.length);
  let cursor = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (true) {
      const i = cursor++;
      if (i >= items.length) return;
      out[i] = await fn(items[i] as T, i);
    }
  });
  await Promise.all(workers);
  return out;
}

export function searchDocumentsTool(
  opts: SearchDocumentsOptions,
): ToolDefinition<SearchDocumentsInput, SearchDocumentsOutput> {
  return {
    name: "search_documents",
    description:
      "Search the document vault by filename, classifier type/year and OCR " +
      "sidecar text. Returns ranked references — vault path, hash, classification " +
      "metadata, and a redacted ±50-character excerpt around the first match. " +
      "Never returns raw file contents; account numbers, IBANs and CPR-shaped " +
      "strings are masked in excerpts before they leave the process.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      const { query, year, type } = args;
      const limit = args.limit ?? DEFAULT_LIMIT;
      const index = readIndex(opts.vaultRoot);

      // Apply the structured filters first so we never even open
      // sidecars for entries that cannot match.
      const candidates: {
        hash: string;
        entry: IndexEntry;
        entryYear: number | null;
        entryType: string;
      }[] = [];
      for (const [hash, entry] of Object.entries(index)) {
        const { year: entryYear, type: entryType } = parseRelPath(entry.path);
        if (year !== undefined && entryYear !== year) continue;
        if (type !== undefined && entryType !== type) continue;
        candidates.push({ hash, entry, entryYear, entryType });
      }

      const hits = (
        await mapWithConcurrency(candidates, SIDECAR_CONCURRENCY, async (cand) => {
          const filename = cand.entry.path.split(/[\\/]/).pop() ?? "";
          const filenameMatches = countOccurrences(filename, query);
          const typeMatches = countOccurrences(cand.entryType, query);

          const ocr = await readSidecar(opts.vaultRoot, cand.entry.path);
          const ocrMatches = countOccurrences(ocr, query);

          const total = filenameMatches + typeMatches + ocrMatches;
          if (total === 0) return null;

          // Excerpt preference: OCR (richest context) → filename →
          // classifier type. Falling back to type ensures hits driven
          // purely by the type filter still surface a meaningful
          // excerpt instead of an unrelated filename slug.
          let excerptSource = "";
          if (ocrMatches > 0) {
            excerptSource = buildExcerpt(ocr, query);
          }
          if (excerptSource === "" && filenameMatches > 0) {
            excerptSource = buildExcerpt(filename, query);
          }
          if (excerptSource === "" && typeMatches > 0) {
            excerptSource = `[type] ${cand.entryType}`;
          }
          if (excerptSource === "") {
            excerptSource = filename;
          }
          const excerpt = redactText(excerptSource);

          return {
            vault_path: cand.entry.path,
            year: cand.entryYear,
            type: cand.entryType,
            classified_at: cand.entry.filed_at,
            hash: cand.hash,
            excerpt,
            matches: total,
          } satisfies ScoredHit;
        })
      ).filter((h): h is ScoredHit => h !== null);

      hits.sort((a, b) => {
        if (b.matches !== a.matches) return b.matches - a.matches;
        // Secondary: newest filed first.
        if (a.classified_at !== b.classified_at) {
          return a.classified_at < b.classified_at ? 1 : -1;
        }
        // Tertiary: vault_path ascending. Returning 0 on equality
        // honours the comparator contract.
        if (a.vault_path === b.vault_path) return 0;
        return a.vault_path < b.vault_path ? -1 : 1;
      });

      return hits.slice(0, limit).map((hit) => ({
        vault_path: hit.vault_path,
        year: hit.year,
        type: hit.type,
        classified_at: hit.classified_at,
        hash: hit.hash,
        excerpt: hit.excerpt,
        confidence: toConfidence(hit.matches),
      }));
    },
  };
}
