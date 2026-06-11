/**
 * MCP tool: `suggest_import_mapping`.
 *
 * Deterministic, rule-based mapping suggestions for the rows of one
 * **staged** import session (ADR-0038). The tool reads staged rows via
 * the same read-only Postgres path as the other MCP tools and returns
 * per-row suggestions for three fields:
 *
 *   - `category`     — canonical spending/investment category derived
 *                      from the row's transaction kind or free text.
 *   - `counterparty` — normalized counterparty / instrument label
 *                      (whitespace collapsed, digits redacted).
 *   - `asset_class`  — coarse asset class keyword-matched from the
 *                      instrument or fund name.
 *
 * Suggestions are PURE suggestions: this tool never writes. Accepting
 * or rejecting happens in the import wizard via the FastAPI import API
 * (`PATCH /imports/{id}/rows/{row_id}`). Excluded rows are skipped —
 * they will not be committed, so suggesting mappings for them would
 * only add noise.
 *
 * Masking rules apply on the way out: every suggested value and reason
 * passes through `redactText` so IBANs, CPR numbers and long digit
 * runs never leave the process (account numbers routinely appear in
 * Nordnet free-text fields like "Internal from 60109543").
 */

import { z } from "zod/v3";

import { redactText } from "../redact.js";
import type { ToolDefinition } from "../registry.js";

const InputSchema = z
  .object({
    import_session_id: z.string().uuid("must be an import session UUID"),
    limit: z.number().int().min(1).max(10_000).optional(),
  })
  .strict();

export type SuggestImportMappingInput = z.infer<typeof InputSchema>;

const DEFAULT_ROW_LIMIT = 1_000;

const SUGGESTION_FIELDS = ["category", "counterparty", "asset_class"] as const;

const SuggestionSchema = z
  .object({
    row_id: z.string(),
    row_index: z.number().int().min(0),
    kind: z.string(),
    field: z.enum(SUGGESTION_FIELDS),
    value: z.string().min(1),
    confidence: z.number().min(0).max(1),
    reason: z.string().min(1),
  })
  .strict();

export type MappingSuggestion = z.infer<typeof SuggestionSchema>;

const OutputSchema = z
  .object({
    session: z
      .object({
        id: z.string(),
        source: z.string(),
        status: z.string(),
        rows_considered: z.number().int().min(0),
      })
      .strict(),
    suggestions: z.array(SuggestionSchema),
  })
  .strict();

export type SuggestImportMappingOutput = z.infer<typeof OutputSchema>;

/** Minimal pg-compatible interface mirroring `NetWorthQueryRunner`. */
export interface ImportMappingQueryRunner {
  query<R extends Record<string, unknown>>(
    sql: string,
    params: ReadonlyArray<unknown>,
  ): Promise<{ rows: R[] }>;
}

export interface SuggestImportMappingOptions {
  runner: ImportMappingQueryRunner;
  /**
   * Fully-qualified import session/row table names. Same trust rules
   * as `martTable` on `query_net_worth`: hard-coded constants or
   * trusted config only — validated as `schema.table`, never user
   * input.
   */
  sessionTable?: string;
  rowTable?: string;
}

const QUALIFIED_IDENT = /^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$/;

function assertQualifiedIdent(value: string, label: string): void {
  if (!QUALIFIED_IDENT.test(value)) {
    throw new Error(
      `${label} must match ${QUALIFIED_IDENT.source} (lowercase schema.table identifier)`,
    );
  }
}

/* ------------------------------------------------------------------ */
/* Deterministic suggestion rules                                      */
/* ------------------------------------------------------------------ */

/**
 * Canonical transaction kinds (shared by the Nordnet and Growney
 * parsers, see `src/penge/ingest/{nordnet,growney}/constants.py`)
 * mapped to category labels. Direct kind mapping is the strongest
 * signal we have, hence the highest confidence.
 */
const CATEGORY_BY_TXN_KIND: Readonly<Record<string, string>> = {
  buy: "investment.trade.buy",
  sell: "investment.trade.sell",
  dividend: "investment.income.dividend",
  cash_interest: "investment.income.interest",
  deposit: "transfer.deposit",
  withdrawal: "transfer.withdrawal",
  internal_transfer: "transfer.internal",
  tax_ask_charge: "tax.ask",
  tax_ask_payment: "tax.ask",
  fee: "cost.fee",
};

const KIND_CONFIDENCE = 0.9;

/** Keyword fallbacks for free text (DA / DE / EN), weaker than kinds. */
const CATEGORY_KEYWORDS: ReadonlyArray<{
  pattern: RegExp;
  category: string;
  confidence: number;
}> = [
  {
    pattern: /geb(?:yr|ühr)|depotf(?:ørelse|ührung)|\bfee\b|kosten/i,
    category: "cost.fee",
    confidence: 0.6,
  },
  {
    pattern: /udbytte|dividende|ausschüttung|dividend/i,
    category: "investment.income.dividend",
    confidence: 0.6,
  },
  {
    pattern: /\brente\b|kreditrente|\bzins(?:en)?\b|interest/i,
    category: "investment.income.interest",
    confidence: 0.55,
  },
  { pattern: /\bskat\b|steuer|\btax\b/i, category: "tax.other", confidence: 0.55 },
  {
    pattern: /indbetaling|einzahlung|\bdeposit\b/i,
    category: "transfer.deposit",
    confidence: 0.55,
  },
  {
    pattern: /udbetaling|auszahlung|withdrawal/i,
    category: "transfer.withdrawal",
    confidence: 0.55,
  },
];

/** Asset-class keyword rules over instrument / fund names. */
const ASSET_CLASS_KEYWORDS: ReadonlyArray<{
  pattern: RegExp;
  assetClass: string;
  confidence: number;
}> = [
  { pattern: /geldmarkt|money market|pengemarked/i, assetClass: "money_market", confidence: 0.7 },
  { pattern: /obligation|\bbond\b|anleihe|renten/i, assetClass: "bond_fund", confidence: 0.7 },
  {
    pattern: /\bgold\b|silver|\bgramm\b|rohstoff|commodit/i,
    assetClass: "commodity",
    confidence: 0.65,
  },
  {
    pattern: /\betf\b|ucits|msci|stoxx|s&p|acwi|\bindex\b|\bworld\b/i,
    assetClass: "equity_etf",
    confidence: 0.7,
  },
];

/** Collapse whitespace and redact digit runs; "" when nothing survives. */
export function normalizeCounterparty(raw: string): string {
  const collapsed = redactText(raw).replace(/\s+/g, " ").trim();
  // A value that is only redaction markers and separators is useless.
  const stripped = collapsed.replaceAll("[REDACTED]", "").replace(/[\s\-–—:.,]/g, "");
  return stripped === "" ? "" : collapsed;
}

interface RowShape {
  id: string;
  row_index: number;
  kind: string;
  payload: Record<string, unknown>;
}

function str(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key];
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function pushCategory(out: MappingSuggestion[], row: RowShape, source: string): void {
  if (row.kind !== "transaction") return;
  // Nordnet stores the canonical kind in `canonical_kind`; Growney in `kind`.
  const txnKind = str(row.payload, "canonical_kind") ?? str(row.payload, "kind");
  if (txnKind !== null && txnKind in CATEGORY_BY_TXN_KIND) {
    out.push({
      row_id: row.id,
      row_index: row.row_index,
      kind: row.kind,
      field: "category",
      value: CATEGORY_BY_TXN_KIND[txnKind] as string,
      confidence: KIND_CONFIDENCE,
      reason: `canonical ${source} transaction kind '${txnKind}' maps directly to this category`,
    });
    return;
  }
  const text = str(row.payload, "text") ?? str(row.payload, "description");
  if (text === null) return;
  for (const rule of CATEGORY_KEYWORDS) {
    if (rule.pattern.test(text)) {
      out.push({
        row_id: row.id,
        row_index: row.row_index,
        kind: row.kind,
        field: "category",
        value: rule.category,
        confidence: rule.confidence,
        reason: redactText(
          `free-text keyword match ${String(rule.pattern)} on the row's transaction text`,
        ),
      });
      return;
    }
  }
}

function pushCounterparty(out: MappingSuggestion[], row: RowShape): void {
  if (row.kind !== "transaction" && row.kind !== "holding") return;
  const instrument =
    str(row.payload, "instrument_name") ??
    str(row.payload, "name") ??
    str(row.payload, "fund_name");
  const freeText = str(row.payload, "text") ?? str(row.payload, "description");
  const raw = instrument ?? freeText;
  if (raw === null) return;
  const normalized = normalizeCounterparty(raw);
  if (normalized === "") return;
  out.push({
    row_id: row.id,
    row_index: row.row_index,
    kind: row.kind,
    field: "counterparty",
    value: normalized,
    confidence: instrument !== null ? 0.7 : 0.5,
    reason:
      instrument !== null
        ? "normalized from the row's instrument name (whitespace collapsed, digits redacted)"
        : "normalized from the row's free text (whitespace collapsed, digits redacted)",
  });
}

function pushAssetClass(out: MappingSuggestion[], row: RowShape, source: string): void {
  if (row.kind === "balance") {
    out.push({
      row_id: row.id,
      row_index: row.row_index,
      kind: row.kind,
      field: "asset_class",
      value: "cash",
      confidence: 0.95,
      reason: "manual balance entries are cash positions by definition",
    });
    return;
  }
  if (row.kind === "scheme") {
    out.push({
      row_id: row.id,
      row_index: row.row_index,
      kind: row.kind,
      field: "asset_class",
      value: "pension",
      confidence: 0.95,
      reason: `${source} scheme rows are pension sub-policies by definition`,
    });
    return;
  }
  if (row.kind !== "holding" && row.kind !== "transaction") return;
  const name =
    str(row.payload, "instrument_name") ??
    str(row.payload, "name") ??
    str(row.payload, "fund_name");
  if (name === null) return;
  for (const rule of ASSET_CLASS_KEYWORDS) {
    if (rule.pattern.test(name)) {
      out.push({
        row_id: row.id,
        row_index: row.row_index,
        kind: row.kind,
        field: "asset_class",
        value: rule.assetClass,
        confidence: rule.confidence,
        reason: `instrument name keyword match ${String(rule.pattern)}`,
      });
      return;
    }
  }
}

/**
 * Pure rule evaluation for one staged row. Exported for unit tests and
 * the eval harness — identical inputs always yield identical output.
 */
export function suggestForRow(source: string, row: RowShape): MappingSuggestion[] {
  const out: MappingSuggestion[] = [];
  pushCategory(out, row, source);
  pushCounterparty(out, row);
  pushAssetClass(out, row, source);
  return out;
}

/* ------------------------------------------------------------------ */
/* Tool definition                                                     */
/* ------------------------------------------------------------------ */

interface SessionRow extends Record<string, unknown> {
  id: string;
  source: string;
  status: string;
}

interface ImportRowRow extends Record<string, unknown> {
  id: string;
  row_index: number;
  kind: string;
  payload: unknown;
}

export function suggestImportMappingTool(
  opts: SuggestImportMappingOptions,
): ToolDefinition<SuggestImportMappingInput, SuggestImportMappingOutput> {
  const sessionTable = opts.sessionTable ?? "public.import_session";
  const rowTable = opts.rowTable ?? "public.import_row";
  assertQualifiedIdent(sessionTable, "sessionTable");
  assertQualifiedIdent(rowTable, "rowTable");

  return {
    name: "suggest_import_mapping",
    description:
      "Deterministic, rule-based mapping suggestions for the rows of one " +
      "staged import session: category (from canonical transaction kinds " +
      "and DA/DE/EN keywords), counterparty normalization (whitespace " +
      "collapsed, digits redacted), and coarse asset-class mapping (from " +
      "instrument-name keywords). Read-only: suggestions are applied or " +
      "rejected exclusively through the import wizard's PATCH endpoint. " +
      "Excluded rows are skipped. Never returns raw account numbers.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      const limit = args.limit ?? DEFAULT_ROW_LIMIT;

      const sessionResult = await opts.runner.query<SessionRow>(
        `SELECT id::text AS id, source, status FROM ${sessionTable} WHERE id = $1::uuid`,
        [args.import_session_id],
      );
      const session = sessionResult.rows[0];
      if (session === undefined) {
        throw new Error(`import session ${args.import_session_id} not found`);
      }
      if (session.status !== "staged") {
        throw new Error(
          `import session ${args.import_session_id} is '${session.status}', not 'staged' — ` +
            "mapping suggestions only apply to staged sessions",
        );
      }

      const rowResult = await opts.runner.query<ImportRowRow>(
        `
          SELECT id::text AS id, row_index, kind, payload
          FROM ${rowTable}
          WHERE session_id = $1::uuid AND excluded = FALSE
          ORDER BY row_index ASC
          LIMIT $2
        `,
        [args.import_session_id, limit],
      );

      const suggestions: MappingSuggestion[] = [];
      for (const raw of rowResult.rows) {
        const payload =
          typeof raw.payload === "object" && raw.payload !== null && !Array.isArray(raw.payload)
            ? (raw.payload as Record<string, unknown>)
            : {};
        const row: RowShape = {
          id: raw.id,
          row_index: Number(raw.row_index),
          kind: raw.kind,
          payload,
        };
        suggestions.push(...suggestForRow(session.source, row));
      }

      return {
        session: {
          id: session.id,
          source: session.source,
          status: session.status,
          rows_considered: rowResult.rows.length,
        },
        suggestions: suggestions.map((s) => ({
          ...s,
          value: redactText(s.value),
          reason: redactText(s.reason),
        })),
      };
    },
  };
}
