/** Connections: link, authorize, and sync Enable Banking bank connections
 * from inside Penge (#230, ADR-0040).
 *
 * The flow mirrors the PSD2 consent dance without a local callback listener:
 *
 *   1. Pick a bank + the person it belongs to → "Start consent" returns the
 *      bank's consent URL (open it, complete SCA in the browser).
 *   2. The callback page shows a `code` (and `state`); paste them back here →
 *      "Authorize" stores the long-lived session (~180 days).
 *   3. "Sync now" pulls transactions + balances into Postgres. Re-syncs reuse
 *      the stored session until it expires — no fresh consent needed.
 *
 * Every failed link/authorize/sync persists a sanitised debug payload that is
 * surfaced inline, so a 422 ALREADY_AUTHORIZED (and friends) is never silent.
 *
 * When the deployment has no signing key the API answers 503; the page then
 * explains the feature is disabled rather than erroring out.
 */

import { useState } from "react";

import { demoMode } from "../api/client";
import {
  useAspsps,
  useAuthorizeConnection,
  useConnections,
  useStartConnectionLink,
  useSyncConnection,
} from "../api/queries";
import type { Connection, ConnectionError, LinkResponse } from "../api/schemas";
import { ErrorState, LoadingState } from "../components/primitives";
import { PengeApiError } from "../errors";

const STATUS_TONE: Readonly<Record<string, string>> = {
  authorized: "good",
  linking: "watch",
  expired: "critical",
  error: "critical",
};

function statusTone(status: string): string {
  return STATUS_TONE[status] ?? "info";
}

function formatTimestamp(value: string | null): string {
  if (value === null) {
    return "—";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

function isDisabled(error: Error): boolean {
  return error instanceof PengeApiError && error.status === 503;
}

export function ConnectionsPage(): React.JSX.Element {
  return (
    <>
      <section className="pageIntro">
        <h1>Bank connections</h1>
        <p>
          Link a bank through Enable Banking, authorize the consent once, then sync on demand. A
          consent is reused for roughly 180 days — only an expired or revoked session asks you to
          consent again.
        </p>
      </section>
      <LinkPanel />
      <AuthorizePanel />
      <ConnectionsList />
    </>
  );
}

function DisabledNote(): React.JSX.Element {
  return (
    <div className="stateBox" role="status">
      <p>
        <strong>Bank connections are disabled in this deployment.</strong>
      </p>
      <p className="stateHint">
        The Enable Banking signing key is not configured here. Mount the key and set{" "}
        <code>ENABLEBANKING_APPLICATION_ID</code> + <code>ENABLEBANKING_KEY_PATH</code> on the API,
        or set <code>VITE_PENGE_DEMO=true</code> for a synthetic walkthrough.
      </p>
    </div>
  );
}

function LinkPanel(): React.JSX.Element {
  const aspsps = useAspsps();
  const startLink = useStartConnectionLink();
  const [provider, setProvider] = useState<string>("");
  const [entityName, setEntityName] = useState<string>("");
  const [result, setResult] = useState<LinkResponse | null>(null);

  if (aspsps.isPending) {
    return (
      <section className="panel">
        <LoadingState label="banks" />
      </section>
    );
  }
  if (aspsps.isError) {
    return (
      <section className="panel">
        {isDisabled(aspsps.error) ? (
          <DisabledNote />
        ) : (
          <ErrorState label="banks" error={aspsps.error} onRetry={() => void aspsps.refetch()} />
        )}
      </section>
    );
  }

  const providers = aspsps.data.providers;
  const selected = provider === "" ? (providers[0]?.provider ?? "") : provider;
  const canSubmit = selected !== "" && entityName.trim() !== "" && !startLink.isPending;

  return (
    <section className="panel">
      <h2>1 · Start a consent</h2>
      <form
        className="connectForm"
        onSubmit={(event) => {
          event.preventDefault();
          if (!canSubmit) {
            return;
          }
          startLink.mutate(
            { provider: selected, entityName: entityName.trim() },
            { onSuccess: (data) => setResult(data) },
          );
        }}
      >
        <label>
          <span>Bank</span>
          <select value={selected} onChange={(event) => setProvider(event.target.value)}>
            {providers.map((aspsp) => (
              <option key={aspsp.provider} value={aspsp.provider}>
                {aspsp.aspsp_name} ({aspsp.aspsp_country})
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Belongs to</span>
          <input
            type="text"
            value={entityName}
            placeholder="e.g. Rouven"
            onChange={(event) => setEntityName(event.target.value)}
          />
        </label>
        <button type="submit" disabled={!canSubmit}>
          {startLink.isPending ? "Starting…" : "Start consent"}
        </button>
      </form>
      {startLink.isError ? (
        <p className="stateDetail" role="alert">
          {startLink.error.message}
        </p>
      ) : null}
      {result !== null ? (
        <div className="consentResult">
          <p>
            Open the consent URL, complete the bank login (SCA), then copy the <code>code</code>{" "}
            (and <code>state</code>) from the callback page into step 2.
          </p>
          <p>
            <a href={result.consent_url} target="_blank" rel="noreferrer">
              Open consent page ↗
            </a>
          </p>
          <dl className="consentMeta">
            <dt>state</dt>
            <dd>
              <code>{result.state}</code>
            </dd>
            <dt>valid until</dt>
            <dd>{formatTimestamp(result.valid_until)}</dd>
          </dl>
        </div>
      ) : null}
    </section>
  );
}

function AuthorizePanel(): React.JSX.Element {
  const authorize = useAuthorizeConnection();
  const [code, setCode] = useState<string>("");
  const [state, setState] = useState<string>("");

  const canSubmit = code.trim() !== "" && !authorize.isPending;

  return (
    <section className="panel">
      <h2>2 · Authorize the callback code</h2>
      <form
        className="connectForm"
        onSubmit={(event) => {
          event.preventDefault();
          if (!canSubmit) {
            return;
          }
          authorize.mutate({
            code: code.trim(),
            state: state.trim() === "" ? undefined : state.trim(),
          });
        }}
      >
        <label>
          <span>Code</span>
          <input
            type="text"
            value={code}
            placeholder="?code= value from the callback"
            onChange={(event) => setCode(event.target.value)}
          />
        </label>
        <label>
          <span>State (optional)</span>
          <input
            type="text"
            value={state}
            placeholder="?state= value"
            onChange={(event) => setState(event.target.value)}
          />
        </label>
        <button type="submit" disabled={!canSubmit}>
          {authorize.isPending ? "Authorizing…" : "Authorize"}
        </button>
      </form>
      {authorize.isError ? (
        <p className="stateDetail" role="alert">
          {authorize.error.message}
        </p>
      ) : null}
      {authorize.isSuccess ? (
        <p className="stateDetail">
          Authorized {authorize.data.aspsp_name}. You can sync it below.
        </p>
      ) : null}
    </section>
  );
}

function ConnectionsList(): React.JSX.Element {
  const connections = useConnections();

  if (connections.isPending) {
    return (
      <section className="panel">
        <LoadingState label="connections" />
      </section>
    );
  }
  if (connections.isError) {
    return (
      <section className="panel">
        {isDisabled(connections.error) ? (
          <DisabledNote />
        ) : (
          <ErrorState
            label="connections"
            error={connections.error}
            onRetry={() => void connections.refetch()}
          />
        )}
      </section>
    );
  }

  const items = connections.data.connections;

  return (
    <section className="panel">
      <h2>Connections</h2>
      {demoMode ? <p className="demoBadge">Demo data — no bank is contacted.</p> : null}
      {items.length === 0 ? (
        <div className="stateBox">
          <p>No bank connections yet. Start a consent above to link your first account.</p>
        </div>
      ) : (
        <ul className="connectionList">
          {items.map((connection) => (
            <ConnectionCard key={connection.id} connection={connection} />
          ))}
        </ul>
      )}
    </section>
  );
}

function ConnectionCard({ connection }: { readonly connection: Connection }): React.JSX.Element {
  const sync = useSyncConnection();

  return (
    <li className="connectionCard">
      <header className="connectionHeader">
        <div>
          <strong>{connection.aspsp_name}</strong>
          <small>
            {connection.entity_name} · {connection.aspsp_country}
          </small>
        </div>
        <span className={`statusPill tone-${statusTone(connection.status)}`}>
          {connection.status}
        </span>
      </header>

      {connection.accounts.length > 0 ? (
        <ul className="accountList">
          {connection.accounts.map((account, index) => (
            <li key={`${connection.id}-${index}`}>
              <span>{account.name ?? "Account"}</span>
              <small>
                {[account.iban_masked, account.currency, account.product]
                  .filter((value): value is string => value !== null && value !== undefined)
                  .join(" · ")}
              </small>
            </li>
          ))}
        </ul>
      ) : (
        <p className="stateHint">No accounts authorized yet.</p>
      )}

      <dl className="connectionMeta">
        <dt>Last sync</dt>
        <dd>
          {formatTimestamp(connection.last_sync_at)}
          {connection.last_sync_status !== null ? ` · ${connection.last_sync_status}` : ""}
        </dd>
        <dt>Valid until</dt>
        <dd>{formatTimestamp(connection.valid_until)}</dd>
      </dl>

      {connection.last_error !== null ? <ErrorDetail error={connection.last_error} /> : null}

      <div className="connectionActions">
        <button
          type="button"
          disabled={sync.isPending}
          onClick={() => sync.mutate({ connectionId: connection.id })}
        >
          {sync.isPending ? "Syncing…" : "Sync now"}
        </button>
        {sync.isError ? (
          <span className="stateDetail" role="alert">
            {sync.error.message}
          </span>
        ) : null}
        {sync.isSuccess ? (
          <span className="stateDetail">
            Imported {sync.data.transactions} transactions, {sync.data.holding_snapshots} snapshots.
          </span>
        ) : null}
      </div>
    </li>
  );
}

function ErrorDetail({ error }: { readonly error: ConnectionError }): React.JSX.Element {
  return (
    <details className="errorDetail">
      <summary>
        Last error in <code>{error.step}</code>
        {error.code !== null && error.code !== undefined ? ` · ${error.code}` : ""}
        {error.status_code !== null && error.status_code !== undefined
          ? ` (HTTP ${error.status_code})`
          : ""}
      </summary>
      <p>{error.message}</p>
      <small>at {formatTimestamp(error.at)}</small>
    </details>
  );
}
