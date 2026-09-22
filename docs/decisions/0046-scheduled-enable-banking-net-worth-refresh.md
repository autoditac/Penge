# 0046 — Scheduled Enable Banking sync and guarded net-worth refresh

- **Status:** Proposed
- **Date:** 2026-09-21
- **Deciders:** @autoditac
- **Tags:** ingest, infra

## Context and Problem Statement

Authorized Enable Banking connections persist reusable sessions, but production
only refreshes them when a user presses **Sync now**.
The React freshness endpoint reads `analytics_marts.mart_net_worth_daily`, so
even a successful ingestion write does not become visible until dbt rebuilds
that mart.
On 2026-09-21 the production mart was still dated 2026-07-25.

The NAS already runs the API and WebUI as root-managed Podman Quadlets.
The automation therefore needs to reuse the API's write database credentials
and Enable Banking key without adding secrets to the repository, isolate a
failing bank connection, avoid overlapping runs, and retain the last validated
analytics output if dbt fails.

## Decision Drivers

- Refresh household balances without a manual ingestion or dbt command.
- Reuse the stored consent and existing connection status/error mechanisms.
- Never let one unavailable ASPSP block another connection.
- Avoid rebuilding analytics after a byte-for-byte idempotent upsert.
- Validate changed analytics before replacing the production net-worth mart.
- Keep credentials in the existing environment file and Podman secret.
- Provide journal-friendly structured events and a concise JSON run summary.

## Considered Options

1. **Quadlet timer plus a typed worker in the API image** — reuse the deployed
   code, credentials, network, and image publication path.
2. **An API-internal scheduler** — start a scheduler thread in every API
   process and couple ingestion lifecycle to the HTTP server.
3. **A NAS checkout running `uv` and dbt from source** — maintain a second
   deployment path and mutable source checkout on production.

## Decision

We chose **Option 1**.

`penge-refresh-net-worth` runs as a one-shot systemd service inside the
health-gated API container at 02:17, 08:17, 14:17, and 20:17 local NAS time,
with up to 15 minutes of randomized delay and `Persistent=true` catch-up after
downtime. Executing in the API container guarantees the worker uses the exact
digest accepted by the API auto-update health check and follows API rollback.
The worker selects `authorized` connections that have a stored session and a
`valid_until` later than the run start.
Retryable sync errors keep that authorized status while recording
`last_sync_status=error`; only an upstream expired/revoked session moves to
`expired`, so transient failures remain eligible at the next trigger.
It invokes the existing `penge.api.connections.service.sync` path for each
connection independently.
Known failures retain the connection service's sanitized `last_error`; an
unexpected per-connection failure is converted to the same sanitized record.
Any failure makes the process exit nonzero, but remaining connections still run.

The Enable Banking loader now distinguishes fetched rows from actual writes.
Its PostgreSQL conflict updates include `IS DISTINCT FROM` predicates and
`RETURNING`, so unchanged transactions, snapshots, accounts, entities, and
instruments report zero writes.
dbt is skipped unless at least one connection changed operational data.
Before each connection can write raw data, a durable `pending` marker is
written to the host-mounted worker state directory. A verified zero-write sync
removes a newly created marker; a sync failure retains it because an earlier
account or fallback window may already have committed. If marker persistence
fails, that connection is not synced and the run exits nonzero.
The marker is removed only after the live dbt run succeeds, so a dbt failure,
container stop, or host restart causes later scheduled runs to retry even when
the next Enable Banking upserts are idempotent.

When data changed, the worker first runs:

```text
dbt build --target refresh
```

The `refresh` target writes and tests the complete analytics graph in isolated
`analytics_refresh_*` schemas. After that build succeeds, one PostgreSQL
transaction renames both live schemas to temporary previous names, promotes
both shadow schemas to the live names, and drops the previous schemas.
Any promotion error rolls back the whole transaction, preserving the complete
prior graph rather than mixing old and new marts.
Shadow schemas are dropped before and after each run.
Refreshing the full graph costs more than selecting only net worth and its
ancestors, but makes schema-level atomic promotion possible and keeps all marts
consistent.

The container and manual CLI share a non-blocking `flock` advisory lock on a
host-mounted file under `/var/lib/penge/refresh`.
systemd also prevents concurrent starts of the same unit, while the shared lock
covers direct container or CLI invocations. The API's manual connection-sync
route takes the same lock and persists the same pending intent before writing,
so it cannot race dbt promotion or lose the retry signal.
The legacy `penge-gls`, `penge-ebank`, and `penge-lunar` sync commands use the
same guard. `PENGE_REFRESH_STATE_DIR` resolves the common state directory:
`.cache/penge-refresh` locally and `/var/lib/penge-refresh` in production.
Lock contention is an explicit nonzero result rather than a second run.

The timer is not configured with automatic retries inside one schedule window.
Enable Banking and dbt failures are visible in the journal and connection
status, and the next six-hour trigger retries naturally.
This avoids an aggressive retry loop against an unavailable bank.

### WebUI-triggered manual refresh (issue #285)

Waiting up to six hours for the next scheduled trigger is sometimes too slow
after a manual import or an ad-hoc bank sync, so the WebUI also exposes a
**Refresh analytics** button that calls `POST /meta/refresh`. This route is a
thin synchronous wrapper around the exact same `DbtRunner.refresh()` path,
shared advisory lock, and durable `pending` marker described above — it does
**not** re-sync any bank connection, and it never runs concurrently with a
connection sync or the scheduled worker because it acquires the identical
`flock` under `PENGE_REFRESH_STATE_DIR`. Like the scheduled worker's own
write-intent tracking, the route persists the `pending` marker *before*
invoking dbt, so a process kill or a dbt failure still leaves durable retry
intent for the next scheduled run; the marker is cleared only once the
shadow build, tests, and atomic promotion have all succeeded (and clearing
is itself best-effort — a filesystem error there is logged but does not turn
an otherwise-successful refresh into an error response). `DbtRunner.refresh()`
similarly treats its own post-promotion shadow-schema cleanup as best-effort,
so a transient error while dropping the now-renamed-away shadow names cannot
misreport an already-committed promotion as a failure. A lock conflict or a
genuine dbt failure otherwise leaves the live marts unchanged and the marker
preserved — or freshly created, if none existed before this trigger — so a
failed manual trigger is indistinguishable (from a data-safety standpoint)
from simply not clicking the button, and the next scheduled run still retries.

Because a dbt build typically takes tens of seconds, the endpoint responds
synchronously rather than returning a job ID to poll — there is no persistent
job queue. Errors are mapped to sanitized, explicit HTTP statuses instead of
leaking subprocess output: `LockUnavailableError`/`RefreshStateError` become
`503 Service Unavailable` (someone else is already refreshing), and
`DbtRefreshError` becomes `502 Bad Gateway` (the shadow build or promotion
failed). The WebUI button disables itself for the duration of the request to
prevent duplicate submissions, and shows an **indeterminate** MUI
`LinearProgress` plus a short status line ("Building and validating
marts…") — a real percentage can't be computed from a `dbt build` run, so a
fake one was rejected as misleading. On success the button's mutation
invalidates the freshness banner and every mart-derived dashboard query so
the refreshed data appears without a manual page reload; the deterministic
demo build resolves immediately with a fixed timestamp instead of touching a
real database.

## Consequences

### Positive

- Net worth converges automatically after real connection writes.
- One bank failure cannot suppress successful ingestion from another.
- Idempotent syncs avoid unnecessary dbt work unless an earlier refresh remains
  pending.
- Failed shadow validation cannot modify live analytics.
- The prior net-worth table remains readable if the live dbt build fails.
- The worker uses the same reviewed, auto-published image as the API.

### Negative

- The API image now includes dbt and the resolved dbt package, increasing its
  size.
- Every changed run builds and tests the full analytics graph.
- A connection failure still makes the overall unit fail even if other banks
  and the mart refresh succeed; operators must inspect the JSON summary.

### Neutral

- Consent expiry still requires user-driven reauthorization.
- Raw ingestion writes are committed before dbt starts; the durable pending
  marker retries them after a dbt failure while keeping the old mart visible.
- The existing manual **Sync now** UI records durable refresh intent; the next
  scheduled worker refreshes dbt.
- The manual **Refresh analytics** WebUI button shares the same lock, marker,
  and `DbtRunner` as the scheduled worker, so it adds no new failure mode; it
  simply lets an operator pull the next scheduled refresh earlier on demand.

## Alternatives in detail

### API-internal scheduler

Rejected because API restarts and horizontal process count would become
scheduling semantics.
It would also mix an independently observable batch job with request serving.

### NAS source checkout

Rejected because production currently deploys immutable GHCR images.
A mutable checkout would require `uv`, Git credentials, dbt dependencies, and a
second rollback procedure on the NAS.

## Links

- [ADR-0040 In-app Enable Banking consent flow](0040-in-app-enable-banking-consent-flow.md)
- [ADR-0044 Continuous image publishing and NAS auto-deploy](0044-continuous-image-publishing-and-nas-auto-deploy.md)
- [NAS deploy and rollback runbook](../runbook/nas-deploy.md)
- `src/penge/ops/net_worth_refresh.py`
- `deploy/nas/penge-net-worth-refresh.{service,timer}`
- Issue #278
- Issue #285
