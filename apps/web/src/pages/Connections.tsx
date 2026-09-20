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

import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Link from "@mui/material/Link";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { demoMode } from "../api/client";
import {
  useAspsps,
  useAuthorizeConnection,
  useConnections,
  useStartConnectionLink,
  useSyncConnection,
} from "../api/queries";
import type { Connection, ConnectionError, LinkResponse } from "../api/schemas";
import { useNotify } from "../components/Notifications";
import { ErrorState, LoadingState, PageHeader, Panel, Pill } from "../components/primitives";
import type { Tone } from "../components/primitives";
import { PengeApiError } from "../errors";

// MUI's "small" TextField input is ~40px tall; bump it to the 44px mobile
// touch-target minimum (#271 acceptance) without switching to the taller
// "medium" size everywhere.
const TOUCH_TARGET_FIELD_SX = { "& .MuiInputBase-root": { minHeight: "2.75rem" } } as const;

const STATUS_TONE: Readonly<Record<string, Tone>> = {
  authorized: "good",
  linking: "watch",
  expired: "critical",
  error: "critical",
};

function statusTone(status: string): Tone {
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
      <PageHeader
        title="Bank connections"
        description="Link a bank through Enable Banking, authorize the consent once, then sync on demand. A consent is reused for roughly 180 days — only an expired or revoked session asks you to consent again."
      />
      <LinkPanel />
      <AuthorizePanel />
      <ConnectionsList />
    </>
  );
}

function DisabledNote(): React.JSX.Element {
  return (
    <Alert severity="info" variant="outlined" sx={{ borderRadius: 3 }}>
      <Box component="strong" sx={{ display: "block" }}>
        Bank connections are disabled in this deployment.
      </Box>
      <Typography sx={{ fontSize: "0.85rem", mt: 0.5 }}>
        The Enable Banking signing key is not configured here. Mount the key and set{" "}
        <code>ENABLEBANKING_APPLICATION_ID</code> + <code>ENABLEBANKING_KEY_PATH</code> on the API,
        or set <code>VITE_PENGE_DEMO=true</code> for a synthetic walkthrough.
      </Typography>
    </Alert>
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
      <Panel eyebrow="1 · Start a consent" title="Link a bank">
        <LoadingState label="banks" />
      </Panel>
    );
  }
  if (aspsps.isError) {
    return (
      <Panel eyebrow="1 · Start a consent" title="Link a bank">
        {isDisabled(aspsps.error) ? (
          <DisabledNote />
        ) : (
          <ErrorState label="banks" error={aspsps.error} onRetry={() => void aspsps.refetch()} />
        )}
      </Panel>
    );
  }

  const providers = aspsps.data.providers;
  const selected = provider === "" ? (providers[0]?.provider ?? "") : provider;
  const canSubmit = selected !== "" && entityName.trim() !== "" && !startLink.isPending;

  return (
    <Panel eyebrow="1 · Start a consent" title="Link a bank">
      <Box
        component="form"
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
        sx={{ display: "flex", flexWrap: "wrap", gap: 1.5, alignItems: "flex-end" }}
      >
        <TextField
          select
          label="Bank"
          value={selected}
          onChange={(event) => setProvider(event.target.value)}
          sx={{ minWidth: "16rem", ...TOUCH_TARGET_FIELD_SX }}
          size="small"
        >
          {providers.map((aspsp) => (
            <MenuItem key={aspsp.provider} value={aspsp.provider}>
              {aspsp.aspsp_name} ({aspsp.aspsp_country})
            </MenuItem>
          ))}
        </TextField>
        <TextField
          label="Belongs to"
          value={entityName}
          placeholder="e.g. Rouven"
          onChange={(event) => setEntityName(event.target.value)}
          size="small"
          sx={TOUCH_TARGET_FIELD_SX}
        />
        <Button type="submit" variant="contained" disabled={!canSubmit} sx={{ minHeight: 44 }}>
          {startLink.isPending ? "Starting…" : "Start consent"}
        </Button>
      </Box>
      {startLink.isError ? (
        <Typography role="alert" color="error.main" sx={{ fontSize: "0.85rem", mt: 1.5 }}>
          {startLink.error.message}
        </Typography>
      ) : null}
      {result !== null ? (
        <Box
          sx={{
            mt: 2,
            p: 1.5,
            borderRadius: 3,
            border: "1px solid",
            borderColor: "divider",
            bgcolor: "background.default",
          }}
        >
          <Typography sx={{ fontSize: "0.9rem" }}>
            Open the consent URL, complete the bank login (SCA), then copy the <code>code</code>{" "}
            (and <code>state</code>) from the callback page into step 2.
          </Typography>
          <Link
            href={result.consent_url}
            target="_blank"
            rel="noreferrer"
            sx={{ display: "inline-block", mt: 1 }}
          >
            Open consent page ↗
          </Link>
          <Stack
            component="dl"
            direction="row"
            spacing={3}
            sx={{ mt: 1.5, mb: 0, flexWrap: "wrap" }}
          >
            <Box component="div" sx={{ m: 0 }}>
              <Typography
                component="dt"
                color="text.secondary"
                sx={{ fontSize: "0.72rem", textTransform: "uppercase" }}
              >
                state
              </Typography>
              <Box component="dd" sx={{ m: 0 }}>
                <Box component="code">{result.state}</Box>
              </Box>
            </Box>
            <Box component="div" sx={{ m: 0 }}>
              <Typography
                component="dt"
                color="text.secondary"
                sx={{ fontSize: "0.72rem", textTransform: "uppercase" }}
              >
                valid until
              </Typography>
              <Box component="dd" sx={{ m: 0 }}>
                {formatTimestamp(result.valid_until)}
              </Box>
            </Box>
          </Stack>
        </Box>
      ) : null}
    </Panel>
  );
}

function AuthorizePanel(): React.JSX.Element {
  const authorize = useAuthorizeConnection();
  const [code, setCode] = useState<string>("");
  const [state, setState] = useState<string>("");
  const notify = useNotify();

  useEffect(() => {
    if (authorize.isSuccess) {
      notify(`Authorized ${authorize.data.aspsp_name}. You can sync it below.`, "success");
    }
  }, [authorize.isSuccess, authorize.data, notify]);

  const canSubmit = code.trim() !== "" && !authorize.isPending;

  return (
    <Panel eyebrow="2 · Authorize the callback code" title="Complete the consent">
      <Box
        component="form"
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
        sx={{ display: "flex", flexWrap: "wrap", gap: 1.5, alignItems: "flex-end" }}
      >
        <TextField
          label="Code"
          value={code}
          placeholder="?code= value from the callback"
          onChange={(event) => setCode(event.target.value)}
          size="small"
          sx={{ minWidth: "16rem", ...TOUCH_TARGET_FIELD_SX }}
        />
        <TextField
          label="State (optional)"
          value={state}
          placeholder="?state= value"
          onChange={(event) => setState(event.target.value)}
          size="small"
          sx={{ minWidth: "12rem", ...TOUCH_TARGET_FIELD_SX }}
        />
        <Button type="submit" variant="contained" disabled={!canSubmit} sx={{ minHeight: 44 }}>
          {authorize.isPending ? "Authorizing…" : "Authorize"}
        </Button>
      </Box>
      {authorize.isError ? (
        <Typography role="alert" color="error.main" sx={{ fontSize: "0.85rem", mt: 1.5 }}>
          {authorize.error.message}
        </Typography>
      ) : null}
    </Panel>
  );
}

function ConnectionsList(): React.JSX.Element {
  const connections = useConnections();

  if (connections.isPending) {
    return (
      <Panel title="Connections">
        <LoadingState label="connections" />
      </Panel>
    );
  }
  if (connections.isError) {
    return (
      <Panel title="Connections">
        {isDisabled(connections.error) ? (
          <DisabledNote />
        ) : (
          <ErrorState
            label="connections"
            error={connections.error}
            onRetry={() => void connections.refetch()}
          />
        )}
      </Panel>
    );
  }

  const items = connections.data.connections;

  return (
    <Panel title="Connections" actions={demoMode ? <Pill tone="watch">Demo data</Pill> : undefined}>
      {items.length === 0 ? (
        <Box
          sx={{
            border: "1px dashed",
            borderColor: "divider",
            borderRadius: 3,
            p: 3,
            color: "text.secondary",
          }}
        >
          No bank connections yet. Start a consent above to link your first account.
        </Box>
      ) : (
        <Stack component="ul" spacing={1.5} sx={{ listStyle: "none", m: 0, p: 0 }}>
          {items.map((connection) => (
            <ConnectionCard key={connection.id} connection={connection} />
          ))}
        </Stack>
      )}
    </Panel>
  );
}

function ConnectionCard({ connection }: { readonly connection: Connection }): React.JSX.Element {
  const sync = useSyncConnection();
  const notify = useNotify();

  useEffect(() => {
    if (sync.isSuccess) {
      notify(
        `Imported ${sync.data.transactions} transactions, ${sync.data.holding_snapshots} snapshots.`,
        "success",
      );
    }
  }, [sync.isSuccess, sync.data, notify]);
  useEffect(() => {
    if (sync.isError) {
      notify(sync.error.message, "error");
    }
  }, [sync.isError, sync.error, notify]);

  return (
    <Box
      component="li"
      sx={{
        border: "1px solid",
        borderColor: "divider",
        borderRadius: 3,
        p: 1.75,
        bgcolor: "background.default",
        display: "flex",
        flexDirection: "column",
        gap: 1,
      }}
    >
      <Stack
        direction="row"
        sx={{ justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 1 }}
      >
        <Box>
          <Box component="strong" sx={{ display: "block" }}>
            {connection.aspsp_name}
          </Box>
          <Typography component="small" color="text.secondary" sx={{ fontSize: "0.82rem" }}>
            {connection.entity_name} · {connection.aspsp_country}
          </Typography>
        </Box>
        <Pill tone={statusTone(connection.status)}>{connection.status}</Pill>
      </Stack>

      {connection.accounts.length > 0 ? (
        <Stack component="ul" spacing={0.5} sx={{ listStyle: "none", m: 0, p: 0 }}>
          {connection.accounts.map((account, index) => (
            <Box component="li" key={`${connection.id}-${index}`} sx={{ fontSize: "0.9rem" }}>
              <Box component="span">{account.name ?? "Account"}</Box>{" "}
              <Typography component="small" color="text.secondary" sx={{ fontSize: "0.8rem" }}>
                {[account.iban_masked, account.currency, account.product]
                  .filter((value): value is string => value !== null && value !== undefined)
                  .join(" · ")}
              </Typography>
            </Box>
          ))}
        </Stack>
      ) : (
        <Typography color="text.secondary" sx={{ fontSize: "0.85rem" }}>
          No accounts authorized yet.
        </Typography>
      )}

      <Stack component="dl" direction="row" spacing={3} sx={{ m: 0, flexWrap: "wrap" }}>
        <Box component="div" sx={{ m: 0 }}>
          <Typography
            component="dt"
            color="text.secondary"
            sx={{ fontSize: "0.72rem", textTransform: "uppercase" }}
          >
            Last sync
          </Typography>
          <Box component="dd" sx={{ m: 0, fontSize: "0.88rem" }}>
            {formatTimestamp(connection.last_sync_at)}
            {connection.last_sync_status !== null ? ` · ${connection.last_sync_status}` : ""}
          </Box>
        </Box>
        <Box component="div" sx={{ m: 0 }}>
          <Typography
            component="dt"
            color="text.secondary"
            sx={{ fontSize: "0.72rem", textTransform: "uppercase" }}
          >
            Valid until
          </Typography>
          <Box component="dd" sx={{ m: 0, fontSize: "0.88rem" }}>
            {formatTimestamp(connection.valid_until)}
          </Box>
        </Box>
      </Stack>

      {connection.last_error !== null ? <ErrorDetail error={connection.last_error} /> : null}

      <Stack direction="row" spacing={1.5} sx={{ alignItems: "center", flexWrap: "wrap" }}>
        <Button
          type="button"
          variant="outlined"
          size="small"
          disabled={sync.isPending}
          onClick={() => sync.mutate({ connectionId: connection.id })}
          sx={{ minHeight: "2.75rem" }}
        >
          {sync.isPending ? "Syncing…" : "Sync now"}
        </Button>
      </Stack>
    </Box>
  );
}

function ErrorDetail({ error }: { readonly error: ConnectionError }): React.JSX.Element {
  return (
    <Box
      component="details"
      sx={{
        fontSize: "0.85rem",
        border: "1px solid",
        borderColor: "error.main",
        borderRadius: 2,
        p: 1,
      }}
    >
      <Box component="summary" sx={{ cursor: "pointer", fontWeight: 600 }}>
        Last error in <code>{error.step}</code>
        {error.code !== null && error.code !== undefined ? ` · ${error.code}` : ""}
        {error.status_code !== null && error.status_code !== undefined
          ? ` (HTTP ${error.status_code})`
          : ""}
      </Box>
      <Typography sx={{ mt: 0.5 }}>{error.message}</Typography>
      <Typography component="small" color="text.secondary" sx={{ fontSize: "0.78rem" }}>
        at {formatTimestamp(error.at)}
      </Typography>
    </Box>
  );
}
