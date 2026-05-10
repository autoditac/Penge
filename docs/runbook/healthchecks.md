# Healthchecks: Uptime Kuma + Sentry

Penge ships two layers of out-of-process observability:

* **Uptime Kuma** — local, self-hosted dashboard that polls long-lived
  HTTP endpoints (the vault watcher's `/health`) and accepts inbound
  push pings from cron-style ingestion jobs.
* **Sentry** — external error tracker for unhandled exceptions in
  ingestion entry points. PII scrubbing is applied before any payload
  leaves the process.

Both layers are **opt-in via env vars**: with `PENGE_UPTIME_KUMA_PUSH_URL`
and `SENTRY_DSN` unset (the default in `.env.example`), the helpers
no-op and ingestion runs unchanged.

See [issue #52](https://github.com/autoditac/Penge/issues/52) for
context and [ADR-0024](../decisions/0024-vault-layout.md) for the
vault watcher health surface this builds on.

## Bring up Uptime Kuma

The Uptime Kuma service is part of the project compose file. Image
digest is pinned; Dependabot (`docker` ecosystem) tracks bumps.

```sh
docker compose up -d uptime-kuma
```

State (monitor configs, heartbeat history, the bcrypt-hashed admin
password) lives in `./data/uptime-kuma` (a SQLite DB) — back it up the
same way as `./data/postgres`.

Open <http://127.0.0.1:3001> and complete the first-run wizard:

1. Pick a username and a *strong* password (the dashboard exposes
   monitor URLs and tokens).
2. Disable any "send anonymous usage statistics" toggle if shown.
3. Under **Settings → Security**, enable 2FA.

The dashboard binds to `127.0.0.1` only. Expose it through a reverse
proxy with TLS + basic auth if you want to read it from another device.

## Monitor: vault watcher `/health`

The vault watcher (`penge-vault watch`) exposes a stdlib HTTP server
on `--health-port` (default: `$PENGE_VAULT_HEALTH_PORT`). `/health`
returns `200 OK` with the heartbeat ISO timestamp and `503 starting`
before the first beat.

In Uptime Kuma, **Add New Monitor → HTTP(s) - Keyword**:

| Field             | Value                                   |
|-------------------|------------------------------------------|
| Friendly name     | `vault-watcher`                          |
| URL               | `http://<host>:9101/health`              |
| Keyword           | `T` (any char from the ISO timestamp)    |
| Heartbeat interval| `60` seconds                             |
| Retries           | `2`                                      |
| Heartbeat retry interval | `60` seconds                      |

Notify channel: pick whatever you already use (email/Pushover/ntfy).

If the watcher pod has no embedded ISO 8601 character to grep for,
swap to **HTTP(s)** monitor type and rely on the `200` status alone.

## Monitor: ingestion job push pings

Cron-driven ingestion jobs have no long-lived endpoint. They use
Uptime Kuma's *Push* monitor type: each successful run hits a unique
URL, and Uptime Kuma alerts when the heartbeat goes stale.

In Uptime Kuma, **Add New Monitor → Push**, one per job:

| Job (component tag)    | Friendly name           | Heartbeat interval |
|------------------------|--------------------------|--------------------|
| `ingest.ecb_fx`        | `ingest-ecb-fx`          | `90` minutes (run daily) |
| `ingest.gls`           | `ingest-gls`             | `26` hours (run daily)   |
| `ingest.ebank`         | `ingest-evangelische`    | `26` hours               |
| `ingest.lunar`         | `ingest-lunar`           | `26` hours               |
| `ingest.nordnet`       | `ingest-nordnet`         | weekly + slack           |
| `ingest.growney`       | `ingest-growney`         | monthly + slack          |
| `ingest.pfa`           | `ingest-pfa`             | yearly + slack           |
| `ingest.prices`        | `ingest-prices`          | daily                    |

Copy the generated push URL (looks like
`http://127.0.0.1:3001/api/push/<token>?status=up&msg=OK&ping=`).

Set the **prefix** (everything before `/<token>`) once in your shell
environment or `.env`:

```sh
PENGE_UPTIME_KUMA_PUSH_URL=http://127.0.0.1:3001/api/push
```

Wire it into the cron wrapper for each job. Example for ECB FX:

```sh
#!/usr/bin/env bash
set -euo pipefail
SLUG="<token-from-uptime-kuma>"
if uv run --group http penge-ecb-fx --latest; then
    uv run --group ops python -c \
        "from penge.ops.heartbeat import heartbeat; heartbeat('$SLUG', 'up', 'ok')"
else
    uv run --group ops python -c \
        "from penge.ops.heartbeat import heartbeat; heartbeat('$SLUG', 'down', 'failed')"
    exit 1
fi
```

Or, better, call `penge.ops.heartbeat.heartbeat(...)` from the same
Python process the job already runs in, e.g. wrapped around the
existing `main()` call site. The helper:

* Reads the prefix from `PENGE_UPTIME_KUMA_PUSH_URL`.
* No-ops silently when the env var is unset.
* Swallows network errors at WARNING level — Uptime Kuma's stale
  heartbeat alert is the source of truth, never the heartbeat call
  itself.
* Uses a 5-second timeout so a hung Uptime Kuma cannot stall ingestion.

## Sentry

`SENTRY_DSN` is read by `penge.ops.sentry.init_sentry()`. All ingestion
CLI entry points (`penge-vault`, `penge-ecb-fx`, `penge-gls`,
`penge-ebank`, `penge-lunar`, `penge-nordnet`, `penge-growney`,
`penge-pfa`, `penge-prices`) call it after `logging.basicConfig()`.

* When unset: `init_sentry()` returns `False` and nothing is sent.
* When set: events are tagged with `component=<entry-point>` and the
  resolved environment (`SENTRY_ENVIRONMENT`, falling back to
  `PENGE_ENV`, default `dev`).

> **Important:** the `sentry-sdk` package only ships with the optional
> `ops` dependency group. Setting `SENTRY_DSN` is **not** sufficient on
> its own — the runtime must also install the group, e.g.
> `uv sync --group ops` (or `uv run --group ops ...`, or include `ops`
> in your container/cron profile). When the SDK is missing,
> `init_sentry()` logs `sentry init skipped: sentry-sdk not installed`
> at WARNING level and returns `False`.

PII scrubbing happens in a `before_send` hook that redacts every dict
value whose key matches `account|iban|cpr|tax_id|name|email`. The same
regex is enforced by the MCP audit logger
(`apps/mcp/src/audit.ts`). If you change one, change both — code review
catches the drift.

### Project setup checklist

1. Create a project in Sentry (Python platform).
2. Copy the DSN into the home server's `.env`.
3. Set `SENTRY_ENVIRONMENT=prod` on the server, `dev` locally.
4. Add `SENTRY_RELEASE=$(git rev-parse --short HEAD)` to the cron
   wrappers so events are pinned to a commit.
5. Verify with a deliberate exception — a one-line script that imports
   `init_sentry`, calls it, then `raise RuntimeError("sentry smoke test")`.
   The event should land in Sentry within seconds, with the
   `account|iban|...` fields redacted in any breadcrumbs.

## Where to look when something fires

| Symptom                                              | Where to look                                       |
|------------------------------------------------------|------------------------------------------------------|
| Uptime Kuma "vault-watcher down"                     | `journalctl --user -u penge-vault.service` (or wherever the watcher runs); `<vault_root>/.health` mtime |
| Uptime Kuma "ingest-* push stale"                    | The cron job's stdout/stderr; `tail -f` the journal log; check `data/postgres` for partial state |
| Sentry event `component=ingest.<x>`                  | The same cron log (full stack trace in Sentry); rerun manually with `--verbose` |
| Sentry event `component=vault-watcher`               | The watcher's stderr; `/metrics` for `vault_failures_total` jumps |

## Troubleshooting

**`heartbeat skipped: PENGE_UPTIME_KUMA_PUSH_URL unset`** (DEBUG log) —
the env var is not set. Either configure it or accept the no-op.

**`sentry init skipped: already initialized`** (DEBUG log) — benign;
`init_sentry()` is safe to call multiple times.

**`sentry init skipped: sentry-sdk not installed`** (WARNING log) —
the `ops` group is not installed. Run `uv sync --group ops` (or include
it in your runtime profile).

**Uptime Kuma state is missing after a restart** — Kuma's SQLite
database lives in the bind mount at `./data/uptime-kuma`. `docker
compose down` (with or without `-v`) does **not** delete bind-mounted
host directories — `-v` only removes Docker-managed named volumes. If
the data directory is empty, it was wiped manually (e.g. `rm -rf
data/uptime-kuma`) or the service was started against a different
working directory; restore from backup and re-create monitors.
