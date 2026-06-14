/** In-memory demo store for bank connections (demo mode only).
 *
 * Mirrors the /connections API semantics deterministically so the link →
 * authorize → sync flow, plus the failed-import debug surface, is
 * exercisable without an Enable Banking signing key or network. Loaded only
 * via dynamic import when `VITE_PENGE_DEMO=true`.
 */

import type {
  Aspsp,
  AspspListResponse,
  Connection,
  ConnectionListResponse,
  LinkResponse,
  SyncResponse,
} from "../api/schemas";
import type { AuthorizeConnectionInput } from "../api/client";

const DEMO_ASPSPS: readonly Aspsp[] = [
  {
    provider: "gls",
    aspsp_name: "GLS Gemeinschaftsbank",
    aspsp_country: "DE",
    default_currency: "EUR",
  },
  {
    provider: "ebank",
    aspsp_name: "Evangelische Bank",
    aspsp_country: "DE",
    default_currency: "EUR",
  },
  { provider: "lunar", aspsp_name: "Lunar", aspsp_country: "DK", default_currency: "DKK" },
] as const;

const ASPSP_BY_PROVIDER = new Map(DEMO_ASPSPS.map((a) => [a.provider, a]));

type StoredConnection = {
  connection: Connection;
  state: string;
};

const connections = new Map<string, StoredConnection>();
let sequence = 0;

const DEMO_NOW = "2026-06-01T09:00:00Z";
const DEMO_VALID_UNTIL = "2026-11-28T09:00:00Z";

function seed(): void {
  if (connections.size > 0) {
    return;
  }
  const id = "demo-connection-0001";
  connections.set(id, {
    state: "demo-state-seeded",
    connection: {
      id,
      provider: "lunar",
      aspsp_name: "Lunar",
      aspsp_country: "DK",
      entity_name: "Rouven",
      status: "authorized",
      valid_until: DEMO_VALID_UNTIL,
      accounts: [
        { name: "Lunar Budget", iban_masked: "DK•••• 3000", currency: "DKK", product: "Current" },
      ],
      last_sync_at: DEMO_NOW,
      last_sync_status: "ok",
      last_error: null,
      created_at: DEMO_NOW,
      updated_at: DEMO_NOW,
    },
  });
}

export function demoListAspsps(): AspspListResponse {
  return { providers: [...DEMO_ASPSPS] };
}

export function demoListConnections(): ConnectionListResponse {
  seed();
  return { connections: [...connections.values()].map((s) => s.connection) };
}

export function demoStartLink(provider: string, entityName: string): LinkResponse {
  const aspsp = ASPSP_BY_PROVIDER.get(provider);
  if (aspsp === undefined) {
    throw new Error(`Unknown provider: ${provider}`);
  }
  sequence += 1;
  const id = `demo-connection-${String(sequence).padStart(4, "0")}-${provider}`;
  const state = `demo-state-${String(sequence).padStart(4, "0")}`;
  connections.set(id, {
    state,
    connection: {
      id,
      provider,
      aspsp_name: aspsp.aspsp_name,
      aspsp_country: aspsp.aspsp_country,
      entity_name: entityName,
      status: "linking",
      valid_until: DEMO_VALID_UNTIL,
      accounts: [],
      last_sync_at: null,
      last_sync_status: null,
      last_error: null,
      created_at: DEMO_NOW,
      updated_at: DEMO_NOW,
    },
  });
  return {
    connection_id: id,
    consent_url: `https://demo.enablebanking.example/auth?state=${state}`,
    state,
    valid_until: DEMO_VALID_UNTIL,
  };
}

export function demoAuthorize(input: AuthorizeConnectionInput): Connection {
  const stored =
    (input.state !== undefined
      ? [...connections.values()].find((s) => s.state === input.state)
      : undefined) ?? [...connections.values()].find((s) => s.connection.status === "linking");
  if (stored === undefined) {
    throw new Error("No pending connection to authorize");
  }
  stored.connection = {
    ...stored.connection,
    status: "authorized",
    accounts: [
      { name: "Demo Current", iban_masked: "DE•••• 3000", currency: "EUR", product: "Current" },
    ],
    last_error: null,
    updated_at: DEMO_NOW,
  };
  return stored.connection;
}

export function demoSync(connectionId: string): SyncResponse {
  const stored = connections.get(connectionId);
  if (stored === undefined) {
    throw new Error("Connection not found");
  }
  stored.connection = {
    ...stored.connection,
    last_sync_at: DEMO_NOW,
    last_sync_status: "ok",
    last_error: null,
    updated_at: DEMO_NOW,
  };
  return { connection: stored.connection, transactions: 12, holding_snapshots: 1 };
}
