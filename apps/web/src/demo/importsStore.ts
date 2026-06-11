/** In-memory demo store for the import wizard (demo mode only).
 *
 * Mirrors the /imports API semantics deterministically so the full wizard
 * flow — upload, review, edit, exclude, commit, discard — is exercisable
 * without a backend. Loaded only via dynamic import when
 * `VITE_PENGE_DEMO=true`.
 */

import type {
  CommitResponse,
  ImportRow,
  ImportSession,
  ImportSessionList,
  ImportSessionWithRows,
} from "../api/schemas";

type StoredSession = {
  session: ImportSession;
  rows: ImportRow[];
};

const sessions = new Map<string, StoredSession>();
let sequence = 0;

const DEMO_TIMESTAMP = "2026-06-01T09:00:00Z";
const DEMO_EXPIRY = "2026-06-08T09:00:00Z";

function recountRows(stored: StoredSession): void {
  const rows = stored.rows;
  stored.session = {
    ...stored.session,
    row_counts: {
      total: rows.length,
      ok: rows.filter((r) => r.status === "ok").length,
      warning: rows.filter((r) => r.status === "warning").length,
      error: rows.filter((r) => r.status === "error").length,
      excluded: rows.filter((r) => r.excluded).length,
    },
  };
}

function demoRows(sessionId: string, source: string): ImportRow[] {
  if (source === "manual_balances") {
    return [
      {
        id: `${sessionId}-row-0`,
        row_index: 0,
        kind: "balance",
        payload: {
          entity: "Person A",
          account_name: "GLS Giro",
          currency: "EUR",
          as_of: "2026-05-31",
          balance: "12450.00",
        },
        status: "ok",
        issues: [],
        edited: false,
        excluded: false,
      },
      {
        id: `${sessionId}-row-1`,
        row_index: 1,
        kind: "balance",
        payload: {
          entity: "Person B",
          account_name: "Lunar Daily",
          currency: "NOT-A-CURRENCY",
          as_of: "2026-05-31",
          balance: "8120.00",
        },
        status: "error",
        issues: [{ code: "invalid", detail: "currency: must be a 3-letter ISO code" }],
        edited: false,
        excluded: false,
      },
    ];
  }
  return [
    {
      id: `${sessionId}-row-0`,
      row_index: 0,
      kind: "transaction",
      payload: {
        nordnet_id: "T1001",
        bookkeeping_date: "2026-05-02",
        account_number: "99999990",
        transaction_type: "INDBETALING",
        amount: "10000.00",
        currency: "DKK",
      },
      status: "ok",
      issues: [],
      edited: false,
      excluded: false,
    },
    {
      id: `${sessionId}-row-1`,
      row_index: 1,
      kind: "transaction",
      payload: {
        nordnet_id: "T1000",
        bookkeeping_date: "2026-05-01",
        account_number: "99999990",
        transaction_type: "KØBT",
        amount: "-5000.00",
        currency: "DKK",
      },
      status: "warning",
      issues: [{ code: "duplicate", detail: "transaction T1000 already exists for this account" }],
      edited: false,
      excluded: false,
    },
  ];
}

function withRows(stored: StoredSession): ImportSessionWithRows {
  return { ...stored.session, rows: [...stored.rows], total_rows: stored.rows.length };
}

function requireSession(sessionId: string): StoredSession {
  const stored = sessions.get(sessionId);
  if (stored === undefined) {
    throw new Error(`demo import session ${sessionId} not found`);
  }
  return stored;
}

export function demoUploadImport(file: File, source?: string): ImportSessionWithRows {
  sequence += 1;
  const id = `demo-import-${sequence}`;
  const resolvedSource =
    source ?? (file.name.endsWith(".json") ? "manual_balances" : "nordnet_transactions");
  const stored: StoredSession = {
    session: {
      id,
      source: resolvedSource,
      original_filename: file.name,
      content_sha256: "d3m0".repeat(16),
      status: "staged",
      params: {},
      error: null,
      created_at: DEMO_TIMESTAMP,
      updated_at: DEMO_TIMESTAMP,
      expires_at: DEMO_EXPIRY,
      committed_at: null,
      row_counts: { total: 0, ok: 0, warning: 0, error: 0, excluded: 0 },
    },
    rows: demoRows(id, resolvedSource),
  };
  recountRows(stored);
  sessions.set(id, stored);
  return withRows(stored);
}

export function demoListImports(): ImportSessionList {
  const all = [...sessions.values()].map((stored) => stored.session).reverse();
  return { sessions: all, total: all.length };
}

export function demoGetImport(sessionId: string): ImportSessionWithRows {
  return withRows(requireSession(sessionId));
}

export function demoPatchImportRow(
  sessionId: string,
  rowId: string,
  patch: {
    payload?: Record<string, unknown> | undefined;
    excluded?: boolean | undefined;
  },
): ImportRow {
  const stored = requireSession(sessionId);
  const index = stored.rows.findIndex((row) => row.id === rowId);
  const row = stored.rows[index];
  if (row === undefined) {
    throw new Error(`demo import row ${rowId} not found`);
  }
  let next: ImportRow = row;
  if (patch.payload !== undefined) {
    const currencyValue = patch.payload["currency"];
    const currencyOk =
      typeof currencyValue !== "string" || /^[A-Za-z]{3}$/.test(currencyValue.trim());
    next = {
      ...next,
      payload: patch.payload,
      edited: true,
      status: currencyOk ? "ok" : "error",
      issues: currencyOk
        ? []
        : [{ code: "invalid", detail: "currency: must be a 3-letter ISO code" }],
    };
  }
  if (patch.excluded !== undefined) {
    next = { ...next, excluded: patch.excluded };
  }
  stored.rows[index] = next;
  recountRows(stored);
  return next;
}

export function demoCommitImport(sessionId: string): CommitResponse {
  const stored = requireSession(sessionId);
  if (stored.session.status !== "staged") {
    throw new Error(`only staged sessions can be committed (status: ${stored.session.status})`);
  }
  const included = stored.rows.filter((row) => !row.excluded);
  if (included.some((row) => row.status === "error")) {
    throw new Error("fix or exclude error rows before committing");
  }
  stored.session = { ...stored.session, status: "committed", committed_at: DEMO_TIMESTAMP };
  const transactions = included.filter((row) => row.kind === "transaction").length;
  const snapshots = included.filter(
    (row) => row.kind === "balance" || row.kind === "holding" || row.kind === "scheme",
  ).length;
  return {
    session: stored.session,
    counts: {
      entities: 1,
      accounts: 1,
      instruments: 0,
      transactions,
      holding_snapshots: snapshots,
    },
  };
}

export function demoDiscardImport(sessionId: string): ImportSession {
  const stored = requireSession(sessionId);
  if (stored.session.status === "committed") {
    throw new Error("committed sessions are kept for audit and cannot be discarded");
  }
  stored.session = { ...stored.session, status: "discarded" };
  return stored.session;
}

/** Test hook: reset the in-memory store between tests. */
export function demoResetImports(): void {
  sessions.clear();
  sequence = 0;
}
