# Monthly automated report

The monthly report bundles the operator-facing numbers for a single
month into two artefacts under `reports/{YYYY-MM}/`:

- `report.md` — Markdown source, embeds the PNG charts via relative paths.
- `report.pdf` — pure-Python PDF (reportlab) with the same content.

Sections: header (month, generated_at, schema versions, git SHA) /
net worth (EoM + MoM/YoY deltas + 12-month sparkline) / cashflow
(in/out/net + top 5 categories) / asset allocation (class +
jurisdiction) / tax preview (DK + DE YTD) / FIRE projection snapshot
(Monte-Carlo P10/P50/P90 + median FIRE year) / operations (vault
inbox stats, last backup age, Sentry error count).

> A section whose source mart / calculator is not yet on `main` is
> rendered as a `**TODO**` block instead of fabricated numbers. This
> is by design: see issue #50.

## On demand

```sh
# default output directory: ./reports
just monthly-report MONTH=2026-04

# or explicitly
uv run --group db --group report python -m penge.ops.report.generate \
    --month 2026-04 --out reports/
```

The Markdown is the source of truth and is portable across viewers.
The PDF is the format archived into Nextcloud as the immutable copy.

## Scheduling

The issue calls for the report to run on the first of every month and
to land in the Nextcloud sync folder. **Do not install the schedulers
from this runbook automatically** — that is an operator decision per
host. Two equivalent patterns:

### systemd-timer (recommended on personal Linux hosts)

Place these under `~/.config/systemd/user/`:

```ini
# ~/.config/systemd/user/penge-monthly-report.service
[Unit]
Description=Penge — monthly PDF + Markdown report

[Service]
Type=oneshot
WorkingDirectory=%h/repositories/Penge
EnvironmentFile=%h/.config/penge/report.env
ExecStart=/usr/bin/env just monthly-report MONTH=$(date -d 'last month' +%%Y-%%m) OUT=%h/Nextcloud/Finance/reports
```

```ini
# ~/.config/systemd/user/penge-monthly-report.timer
[Unit]
Description=Run the Penge monthly report on the 1st of each month

[Timer]
OnCalendar=*-*-01 06:30:00
Persistent=true
Unit=penge-monthly-report.service

[Install]
WantedBy=timers.target
```

Then:

```sh
systemctl --user daemon-reload
systemctl --user enable --now penge-monthly-report.timer
systemctl --user list-timers penge-monthly-report.timer
```

### cron (portable fallback)

```cron
# m h dom mon dow  command
30 6 1 * *  cd "$HOME/repositories/Penge" && \
    just monthly-report MONTH="$(date -d 'last month' +\%Y-\%m)" \
        OUT="$HOME/Nextcloud/Finance/reports" \
    >> "$HOME/.local/state/penge/monthly-report.log" 2>&1
```

Either pattern should be wired through the existing healthcheck
heartbeat (see [`healthchecks.md`](healthchecks.md)) so a missed
month surfaces in Uptime Kuma.

## Privacy

Every string field that lands in the report passes through the same
redaction regex used by `penge.ops.sentry` and the MCP audit logger
(`account|iban|cpr|tax_id|name|email`, plus inline IBAN / CPR /
email pattern matches). The end-to-end test in
`tests/ops/report/test_generate.py` asserts that a synthetic IBAN
inserted into a category label is replaced with `[REDACTED]` in the
rendered Markdown.

`reports/` is gitignored.
