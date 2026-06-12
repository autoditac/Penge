/** Typed fetch client for the Penge read API (ADR-0035, ADR-0036).
 *
 * Every response is validated with the zod schemas in `schemas.ts` before it
 * reaches the UI. Failures surface as `PengeApiError` with a machine code.
 */

import type { ZodType } from "zod";

import { PengeApiError } from "../errors";
import {
  accountsResponseSchema,
  allocationResponseSchema,
  cashflowSeriesResponseSchema,
  commitResponseSchema,
  freshnessResponseSchema,
  importRowSchema,
  importSessionListSchema,
  importSessionSchema,
  importSessionWithRowsSchema,
  netWorthSeriesResponseSchema,
  netWorthTotalSeriesResponseSchema,
  suggestionsResponseSchema,
} from "./schemas";
import type {
  AccountSummary,
  AllocationDimension,
  AllocationResponse,
  CashflowSeriesResponse,
  CommitResponse,
  FreshnessResponse,
  ImportRow,
  ImportSession,
  ImportSessionList,
  ImportSessionWithRows,
  NetWorthSeriesResponse,
  NetWorthTotalSeriesResponse,
  SuggestionsResponse,
} from "./schemas";

export const apiBaseUrl: string = import.meta.env.VITE_PENGE_API_URL ?? "http://127.0.0.1:8000";

/** True when the UI serves deterministic synthetic fixtures instead of the API. */
export const demoMode: boolean = import.meta.env.VITE_PENGE_DEMO === "true";

export type SeriesParams = {
  readonly since?: string;
  readonly until?: string;
  readonly limit?: number;
};

async function getJson<T>(
  path: string,
  params: Readonly<Record<string, string | number | undefined>>,
  schema: ZodType<T>,
): Promise<T> {
  return requestJson(path, { params }, schema);
}

type RequestOptions = {
  readonly method?: string;
  readonly params?: Readonly<Record<string, string | number | undefined>>;
  readonly jsonBody?: unknown;
  readonly formBody?: FormData;
};

/** Extract the FastAPI `detail` string from a 4xx/5xx body, if present. */
function errorDetail(payload: unknown): string | null {
  if (typeof payload === "object" && payload !== null && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") {
      return detail;
    }
  }
  return null;
}

async function requestJson<T>(
  path: string,
  options: RequestOptions,
  schema: ZodType<T>,
): Promise<T> {
  const url = new URL(path, apiBaseUrl);
  for (const [key, value] of Object.entries(options.params ?? {})) {
    if (value !== undefined) {
      url.searchParams.set(key, String(value));
    }
  }

  const headers: Record<string, string> = { Accept: "application/json" };
  let body: BodyInit | undefined;
  if (options.formBody !== undefined) {
    body = options.formBody; // fetch sets the multipart boundary itself
  } else if (options.jsonBody !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.jsonBody);
  }

  let response: Response;
  try {
    response = await fetch(url, { method: options.method ?? "GET", headers, body: body ?? null });
  } catch (cause) {
    throw new PengeApiError(
      "api_unreachable",
      `Penge API at ${apiBaseUrl} is unreachable: ${cause instanceof Error ? cause.message : String(cause)}`,
    );
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch (cause) {
    if (!response.ok) {
      throw new PengeApiError(
        "api_http_error",
        `Penge API returned ${response.status} for ${path}.`,
        response.status,
      );
    }
    throw new PengeApiError(
      "api_invalid_json",
      `Penge API response for ${path} is not valid JSON: ${cause instanceof Error ? cause.message : String(cause)}`,
      response.status,
    );
  }

  if (!response.ok) {
    const detail = errorDetail(payload);
    throw new PengeApiError(
      "api_http_error",
      detail ?? `Penge API returned ${response.status} for ${path}.`,
      response.status,
    );
  }

  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    throw new PengeApiError(
      "api_schema_mismatch",
      `Penge API response for ${path} failed schema validation: ${parsed.error.message}`,
      response.status,
    );
  }
  return parsed.data;
}

export function fetchAccounts(): Promise<readonly AccountSummary[]> {
  return getJson("/accounts", {}, accountsResponseSchema);
}

export function fetchAllocation(by: AllocationDimension): Promise<AllocationResponse> {
  return getJson("/allocation/current", { by }, allocationResponseSchema);
}

export function fetchNetWorthTotal(params: SeriesParams): Promise<NetWorthTotalSeriesResponse> {
  return getJson(
    "/net-worth/daily",
    { group: "total", ...params },
    netWorthTotalSeriesResponseSchema,
  );
}

export function fetchNetWorthByAccount(params: SeriesParams): Promise<NetWorthSeriesResponse> {
  return getJson("/net-worth/daily", { group: "account", ...params }, netWorthSeriesResponseSchema);
}

export function fetchCashflowDaily(params: SeriesParams): Promise<CashflowSeriesResponse> {
  return getJson("/cashflow/daily", { ...params }, cashflowSeriesResponseSchema);
}

export function fetchFreshness(): Promise<FreshnessResponse> {
  return getJson("/meta/freshness", {}, freshnessResponseSchema);
}

/* ---- import sessions (#207/#208) ---- */

export type UploadImportOptions = {
  readonly source?: string | undefined;
  readonly entityName?: string | undefined;
  readonly accountName?: string | undefined;
};

export function uploadImport(
  file: File,
  options: UploadImportOptions = {},
): Promise<ImportSessionWithRows> {
  const form = new FormData();
  form.set("file", file, file.name);
  if (options.source !== undefined && options.source !== "") {
    form.set("source", options.source);
  }
  if (options.entityName !== undefined && options.entityName !== "") {
    form.set("entity_name", options.entityName);
  }
  if (options.accountName !== undefined && options.accountName !== "") {
    form.set("account_name", options.accountName);
  }
  return requestJson("/imports", { method: "POST", formBody: form }, importSessionWithRowsSchema);
}

export function fetchImportSessions(): Promise<ImportSessionList> {
  return getJson("/imports", {}, importSessionListSchema);
}

/** Matches the API's DEFAULT_ROW_LIMIT; MAX_ROW_LIMIT is 10_000. */
const importRowPageSize = 1_000;

/** Fetch a staged session with ALL rows, following `limit`/`offset` pagination
 * until `rows.length === total_rows` so review and commit gating never operate
 * on a partial first page. */
export async function fetchImportSession(sessionId: string): Promise<ImportSessionWithRows> {
  const first = await getJson(
    `/imports/${sessionId}`,
    { limit: importRowPageSize, offset: 0 },
    importSessionWithRowsSchema,
  );
  const rows = [...first.rows];
  while (rows.length < first.total_rows) {
    const page = await getJson(
      `/imports/${sessionId}`,
      { limit: importRowPageSize, offset: rows.length },
      importSessionWithRowsSchema,
    );
    if (page.rows.length === 0) {
      break; // defensive: total_rows shrank mid-pagination (concurrent edit)
    }
    rows.push(...page.rows);
  }
  return { ...first, rows };
}

export type RowPatch = {
  readonly payload?: Record<string, unknown> | undefined;
  readonly excluded?: boolean | undefined;
  readonly mappings?: Record<string, string> | undefined;
  readonly suggestedBy?: string | undefined;
};

export function patchImportRow(
  sessionId: string,
  rowId: string,
  patch: RowPatch,
): Promise<ImportRow> {
  const body: Record<string, unknown> = {};
  if (patch.payload !== undefined) {
    body["payload"] = patch.payload;
  }
  if (patch.excluded !== undefined) {
    body["excluded"] = patch.excluded;
  }
  if (patch.mappings !== undefined) {
    body["mappings"] = patch.mappings;
  }
  if (patch.suggestedBy !== undefined) {
    body["suggested_by"] = patch.suggestedBy;
  }
  return requestJson(
    `/imports/${sessionId}/rows/${rowId}`,
    { method: "PATCH", jsonBody: body },
    importRowSchema,
  );
}

/** Ask the MCP suggestion tool for mapping proposals. The API answers 503
 * when no MCP command is configured — callers must degrade gracefully. */
export function fetchImportSuggestions(sessionId: string): Promise<SuggestionsResponse> {
  return requestJson(
    `/imports/${sessionId}/suggestions`,
    { method: "POST" },
    suggestionsResponseSchema,
  );
}

export type CommitOptions = {
  readonly entityName?: string | undefined;
  readonly accountName?: string | undefined;
};

export function commitImport(
  sessionId: string,
  options: CommitOptions = {},
): Promise<CommitResponse> {
  const body: Record<string, string> = {};
  if (options.entityName !== undefined && options.entityName !== "") {
    body["entity_name"] = options.entityName;
  }
  if (options.accountName !== undefined && options.accountName !== "") {
    body["account_name"] = options.accountName;
  }
  return requestJson(
    `/imports/${sessionId}/commit`,
    { method: "POST", jsonBody: body },
    commitResponseSchema,
  );
}

export function discardImport(sessionId: string): Promise<ImportSession> {
  return requestJson(`/imports/${sessionId}`, { method: "DELETE" }, importSessionSchema);
}
