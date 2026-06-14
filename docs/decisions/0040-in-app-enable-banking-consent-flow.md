# 0040 — In-app Enable Banking consent flow

- **Status:** Proposed
- **Date:** 2026-06-13
- **Deciders:** @autoditac
- **Tags:** ingest, web, security

## Context and Problem Statement

Real-account ingestion from Enable Banking (EB, PSD2; see ADR-0026) currently
runs only through per-bank CLIs. The consent dance is awkward and fragile:

1. A CLI prints a consent URL; the user completes Strong Customer
   Authentication (SCA) in a browser.
2. The callback page shows a one-time `code`.
3. A second CLI call exchanges that `code` for an EB **session** and
   immediately pulls transactions.

The session id — the credential that authorises subsequent reads — is **only
printed to stdout and never persisted**. A consent (session) is valid for
roughly 180 days, but because nothing stores it, every re-sync forces a fresh
SCA. Worse, a `code` is single-use: if a sync run is interrupted after the
exchange, the session id is lost and the consent must be redone. This is
exactly the failure the household hit in production (three `422
ALREADY_AUTHORIZED` responses with unrecoverable session ids).

There is also no surfaced debug information: a failed authorize/sync vanishes
into CLI output. We need the flow inside the Penge UI, with persisted sessions
and visible, sanitised error state — without weakening the LLM/data trust
boundary (ADR-0005) or leaking the EB private key.

## Decision Drivers

- **Re-use consent.** A 180-day session should be stored so re-syncs do not
  require new SCA until expiry or revocation.
- **Debuggability.** Failed link/authorize/sync must leave a visible,
  sanitised trace, not just CLI stdout.
- **Trust boundary.** The EB RSA private key signs every request and must live
  only where the API runs. The public NAS instance must not silently expose a
  bank-linking surface if it has no key.
- **No new LLM data path.** This is plumbing, not analysis; it must not route
  raw statement data through any LLM (ADR-0005 stays intact).
- **Reversible + typed.** Follow the repo contract: a reversible migration,
  Pydantic at the boundary, zod + generated OpenAPI types in the UI.

## Considered Options

1. **Persist sessions in a new `bank_connection` table + gated API + UI.**
   Store the session id and metadata server-side; expose a `/connections`
   surface; gate the whole feature on the presence of the signing key.
2. **Keep the CLIs, only add a session cache file.** Persist the session id to
   a local file the CLIs read. No UI, no API, no NAS story.
3. **Full in-app OAuth-style callback listener.** Register an HTTP callback in
   the API that receives the `code` directly, removing the copy-paste step.

## Decision

We chose **Option 1**.

A new singular `bank_connection` table (migration `0006`) persists, per
connection: provider, ASPSP name/country, entity, status, the consent `state`,
the EB `session_id`, `valid_until`, the authorised `accounts`, and the
`last_sync_*` / `last_error` debug fields. The `session_id` is **never**
serialised back to the client — only its derived status is exposed.

A new `penge.api.connections` FastAPI router exposes:

- `GET /connections/aspsps` — banks this deployment can connect to.
- `GET /connections` — all connections with status + sanitised `last_error`.
- `POST /connections/link` — start a consent, returns the bank's consent URL.
- `POST /connections/authorize` — exchange the callback `code` (+ `state`) for
  a stored session.
- `POST /connections/{id}/sync` — pull transactions + balances into Postgres,
  reusing the stored session.

The whole router is **feature-gated**: `ConnectionsConfig.enabled` is true only
when `ENABLEBANKING_APPLICATION_ID` + `ENABLEBANKING_KEY_PATH` are set and the
key file exists (with a `PENGE_CONNECTIONS_ENABLED` kill switch). When
disabled, every endpoint returns `503`, and the UI shows a "disabled in this
deployment" note instead of an error.

The UI keeps the **copy-paste callback** rather than an in-app listener
(Option 3 is deferred): step 1 starts the consent and shows the URL; the user
completes SCA and pastes the `code`/`state` from the static callback page; step
2 authorizes; each connection then has a "Sync now" button. This avoids
registering and securing a new public callback endpoint for now.

**Answer to "will every import require consent?"** No. Consent is required only
the first time and again when the stored session expires (~180 days) or is
revoked by the bank/user. Normal re-syncs reuse the persisted session.

## Consequences

### Positive

- Re-syncs no longer trigger SCA until the session genuinely expires.
- An interrupted authorize no longer strands the session id; it is committed
  before the first sync.
- Failed imports leave a sanitised, queryable `last_error` (step, status code,
  EB error code, message, timestamp) surfaced directly in the UI.
- The public NAS instance stays safe by default: no key → `503`, no surface.

### Negative

- To enable on the NAS, the EB private key must be mounted into the
  `penge-api` container (podman secret) and `ENABLEBANKING_*` env set — a
  deliberate, documented operational step, not a default.
- The copy-paste callback is still manual; a smoother in-app callback is
  deferred (Option 3).

### Neutral

- `bank_connection` stores a long-lived credential (`session_id`). It is a
  bearer token for read-only account access, never returned to clients, and is
  covered by the same backup/encryption posture as the rest of Postgres.

## Alternatives in detail

### Option 2 — session cache file for the CLIs

Smallest change, but leaves the flow CLI-only, gives no UI/NAS story, and a
flat file is a poor home for a per-connection credential with status and error
history. Rejected.

### Option 3 — in-app callback listener

Best UX (no copy-paste), but requires a new public, unauthenticated callback
endpoint that accepts an EB `code`, plus CSRF/`state` hardening on the public
instance. Deferred until the consent surface has proven itself; the persisted
`state` column already prepares for it.

## Links

- ADR-0005 — LLM access via MCP only (trust boundary preserved).
- ADR-0026 — Retire GoCardless; standardize on Enable Banking for PSD2.
- ADR-0037 — Staged import sessions (sibling write-path surface).
- Code: `src/penge/api/connections/`, `migrations/versions/0006_add_bank_connection.py`,
  `apps/web/src/pages/Connections.tsx`.
- Runbook: `docs/runbook/enable-banking-consent.md`.
- Issue #230.
