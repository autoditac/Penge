# Web dashboard

The Penge dashboard is a [Streamlit](https://streamlit.io/) app that
renders the marts produced by dbt — net worth over time, today's
KPIs, allocation pies, and per-account drill-down. It is the v1 surface
described in [issue #25](https://github.com/autoditac/Penge/issues/25).

The modern WebUI direction is documented in
[Modern WebUI](../web/modern-webui.md) and
[ADR-0033](../decisions/0033-reporting-first-react-webui.md).
That React shell starts with synthetic reporting data and is intended to absorb
the richer cockpit, planning-lab, and AI-assistant surfaces over time.

## Threat model

Treat the dashboard as **read-only and personally identifying**: it
shows account balances, IBANs, and provider names. It performs **no
authentication of its own** — protect it at the network layer.

Default posture: **bind to localhost** and reach it over a private
overlay network (Tailscale) or behind a fronting reverse proxy that
enforces auth (Caddy basic-auth, OIDC).

Account identifiers (IBANs, last-4 suffix in the account display name)
are masked by default. The sidebar checkbox **Reveal account
identifiers** unmasks them for the current session only.

## Run locally

```bash
uv sync --group web --group db
export DATABASE_URL=postgresql+psycopg://penge:penge@localhost:5432/penge
uv run --group web --group db penge-web
```

Streamlit binds to `localhost:8501` by default. Visit
<http://localhost:8501>.

The dashboard reads from `analytics_marts.mart_net_worth_daily` and the
`account` / `entity` tables. If the marts are empty you will see "No
data yet" placeholders — populate them by running the loaders and then
`uv run --group dbt dbt build`.

## Deploy via Tailscale (preferred)

Run the dashboard on the same host as Postgres and join it to your
Tailnet. Bind Streamlit to the Tailscale IP so it is reachable only
from devices on your tailnet:

```bash
# Adjust to your tailnet IP (`tailscale ip -4`).
penge-web --server.address 100.64.0.1 --server.port 8501
```

A systemd unit, on a self-hosted box:

```ini
# /etc/systemd/system/penge-web.service
[Unit]
Description=Penge Streamlit dashboard
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=penge
WorkingDirectory=/opt/penge
EnvironmentFile=/etc/penge/web.env
ExecStart=/usr/bin/uv run --group web --group db penge-web \
  --server.address 100.64.0.1 --server.port 8501
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

`/etc/penge/web.env` should contain at minimum `DATABASE_URL`.

## Deploy behind Caddy basic-auth

If Tailscale is not an option, terminate TLS and require HTTP basic
auth at a Caddy reverse proxy:

```caddy
penge.example.internal {
    basic_auth {
        # bcrypt hash; generate with `caddy hash-password`.
        admin $2a$14$REDACTED
    }
    reverse_proxy 127.0.0.1:8501
}
```

Run Streamlit bound to localhost only:

```bash
penge-web --server.address 127.0.0.1 --server.port 8501
```

## Tests

A headless smoke test in `tests/web/test_app_smoke.py` drives the app
via `streamlit.testing.v1.AppTest` against synthetic data. It runs in
CI as part of the `pytest` job. A Playwright/screenshot regression is a
follow-up — the smoke test is enough to catch import errors and
basic render breakage in the four views.

The React WebUI has its own pnpm quality gates:

```bash
just web-ui-build
just web-ui-test
just web-ui-lint
```

The WebUI also has a container image.
See [Container images](container-images.md) for local builds and release image
publishing.
