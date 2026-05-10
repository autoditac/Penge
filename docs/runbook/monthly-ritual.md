# Monthly ritual (1-hour close)

Once a month — typically the first weekend after all statements have
landed in the inbox — the operator works through this checklist to
close the previous month: refresh ingestion, rebuild dbt, sanity-check
the dashboard, take a tax preview, and confirm backups are healthy.

**Target wall-clock:** ~60 minutes.

If a step takes substantially longer than the budget below, **stop and
diagnose** rather than push through; the ritual is meant to surface
problems, not paper over them. All numbers, paths, and entity names in
this page are illustrative.

## Prerequisites

- Working tree on `main`, with `just bootstrap` having succeeded at
  least once (see [CONTRIBUTING.md](https://github.com/autoditac/Penge/blob/main/CONTRIBUTING.md)).
- Local Postgres + DuckDB reachable; Compose stack running.
- `~/Nextcloud/Finance/inbox/` and `~/Nextcloud/Finance/vault/` synced
  on this host.
- `PENGE_BACKUP_RECIPIENTS` and `PENGE_BACKUP_IDENTITY_FILE` exported,
  per [Encrypted backups](backup-restore.md).
- Optional but recommended: Sentry DSN and Uptime Kuma push URL set so
  step 3 has somewhere to look (see
  [Healthchecks](healthchecks.md)).

---

## 1. Prep — 5 min

```bash
cd ~/repositories/Penge
git fetch origin
git checkout main
git pull --ff-only

just up                     # Postgres + Adminer + Uptime Kuma
just migrate-up             # idempotent; no-op if already at head
```

### What "good" looks like

- `git pull` says `Already up to date.` or fast-forwards cleanly.
- `docker compose ps` lists `penge-postgres-1` and `penge-adminer-1`
  as `running (healthy)`.
- `alembic upgrade head` prints `INFO  [alembic.runtime.migration]`
  lines and returns `0`.
- Last successful backup run is visible:

  ```bash
  ls -lh "${PENGE_BACKUP_ROOT:-./backups}/postgres" | tail -3
  ```

  The newest `pg-*.sql.age` should be ≤ 24 h old; if not, see
  [Encrypted backups → Scheduling](backup-restore.md#scheduling).

### Common failures

- `pull` reports a merge conflict → you have local commits on `main`;
  branch them off (`git switch -c rescue/$(date +%F)`) before
  retrying. The repo's [Working Contract](https://github.com/autoditac/Penge/blob/main/AGENTS.md) forbids
  direct `main` commits.
- Compose container `unhealthy` → `docker compose logs postgres` and
  fix before continuing. Skipping is not an option; subsequent steps
  write to that database.

---

## 2. Drop statements into the vault inbox — 10 min

Collect every statement issued for the closed month — Nordnet
transaction CSVs, PFA Pensionsoversigt (annual), Growney/Sutor
Depotauszug (quarterly), GLS/Ev.Bank/Lunar PDF Kontoauszüge, payroll
slips — and drop them into:

```text
~/Nextcloud/Finance/inbox/
```

The vault watcher (issue
[#41](https://github.com/autoditac/Penge/issues/41), see
[Vault watcher](vault-watcher.md)) is expected to be running on the
home server. It OCRs each PDF, the rule-based classifier (issue
[#42](https://github.com/autoditac/Penge/issues/42)) tags it, and the
file is moved into:

```text
~/Nextcloud/Finance/vault/<year>/<category>/<hash>-<slug>.pdf
```

### What "good" looks like

- The inbox empties within ~60 s per file.
- `vault_files_filed_total` (visible at `http://<watcher-host>:9101/metrics`)
  ticks up; `vault_failures_total` stays at `0`.
- Each new file appears under the expected `<category>` folder.

### Manual triage

Anything the classifier could not assign with confidence lands under
`vault/<year>/unsorted/`. Open that directory and either:

1. Move the file into the correct category folder by hand (the SHA in
   the filename keeps the index honest), or
2. File a small PR strengthening
   `src/penge/vault/classifier_rules.yaml` and re-run the watcher with
   `--once` against an empty inbox, per
   [Vault watcher → Tuning the rules](vault-watcher.md#tuning-the-rules).

ADR context: [ADR-0024 — Vault layout](../decisions/0024-vault-layout.md).

---

## 3. Refresh ingestion — 10 min

Run the connectors that have data for the closed month. Each is a
separate recipe — there is no aggregate `just ingest` today; this is
deliberate so a flaky third-party API does not kill the rest of the
batch. See [ADR-0003 — Hybrid ingestion](../decisions/0003-hybrid-ingestion-psd2-and-csv-pdf.md).

### Daily-rate FX (always run)

```bash
uv run --group db penge-ecb-fx --90d
```

`--90d` overlaps the previous run so a missed weekday or upstream
outage gets back-filled. See
[ECB daily FX rates](../connectors/ecb_fx.md).

### PSD2 banks (Enable Banking)

```bash
just ingest-gls    sync --entity-name "Operator A" --days 45
just ingest-ebank  sync --entity-name "Operator A" --days 45
just ingest-lunar  sync --entity-name "Operator B" --days 45
```

`--days 45` deliberately overlaps the previous run so a delayed
booking still gets caught. Re-running is idempotent — duplicates
are deduped by `(account_id, provider_tx_id)`.

If `authorize` is required (PSD2 consents expire every 90 days), the
CLI prints the URL to follow; run `just ingest-<bank> link` first,
then `authorize --code <CODE>`.

### Custodians (CSV / PDF)

```bash
# Nordnet — monthly CSV export. See docs/connectors/nordnet.md for
# the accounts-config YAML schema.
uv run --group db penge-nordnet \
    --transactions ~/Nextcloud/Finance/vault/$(date +%Y)/depotauszug/nordnet-transactions-*.csv \
    --holdings    ~/Nextcloud/Finance/vault/$(date +%Y)/depotauszug/nordnet-depotoversigt-*.csv \
    --accounts-config config/nordnet-accounts.yaml

# Growney / Sutor — quarterly PDF (skip outside quarter-end months)
just ingest-growney --entity-name "Operator A" \
    ~/Nextcloud/Finance/vault/$(date +%Y)/depotauszug/sutor-*.pdf

# PFA pension — annual; only on the once-a-year delivery
just ingest-pfa --entity-name "Operator A" \
    ~/Nextcloud/Finance/vault/$(date +%Y)/pfa-statement/pensionsoversigt-*.pdf
```

### Manual entries

Anything not covered by a connector — cash balances, real-estate
valuations:

```bash
just manual-add-balance --entity "Operator A" \
    --account "DKB Tagesgeld" --currency EUR --balance 12345.67
just manual-mark-property --entity "Operator A" \
    --account "Nederbyvej 36" --property "Nederbyvej 36 (DK)" \
    --currency DKK --valuation 4500000
```

### Prices

```bash
uv run --group db --group prices penge-prices --last-30d
```

`--last-30d` is the standard monthly cadence; pair with
`--nordnet-holdings <Depotoversigt.csv>` if you want a same-run
cross-check against Nordnet's last-quote column.

### What "good" looks like

- Each connector exits `0` and prints a one-line summary
  (`✓ inserted N transactions, N balances, …`).
- Sentry dashboard shows zero new ingestion errors since the last
  ritual; Uptime Kuma "vault-watcher" monitor is green
  ([Healthchecks](healthchecks.md)).

### Common failures

| Symptom | Where to look |
| --- | --- |
| `401 Unauthorized` from Enable Banking | Consent expired; re-run `link` + `authorize`. |
| Nordnet parser raises `ValueError` on a header | Schema drift; open an issue, attach the offending header line (with values redacted). |
| PFA OCR fallback fails | Confirm `tesseract`, `tesseract-ocr-dan`, `tesseract-ocr-deu` installed on host. |
| Sentry shows new errors | Click through; do not proceed past step 4 with unresolved ingestion errors. |

---

## 4. Run dbt — 5 min

```bash
uv run --group dbt dbt build --project-dir dbt --profiles-dir dbt
```

(There is no `just dbt-build` recipe today; add one if you find
yourself typing this often.)

### What "good" looks like

- Final summary reads `Done. PASS=N WARN=0 ERROR=0 SKIP=0 TOTAL=N`.
- `analytics_marts.mart_net_worth_daily` has a row for every day up
  to and including yesterday:

  ```bash
  # DATABASE_URL in the repo is a SQLAlchemy URL
  # (postgresql+psycopg://…); strip the dialect prefix for libpq tools.
  psql "${DATABASE_URL/+psycopg/}" -c \
    "select max(asof_date) from analytics_marts.mart_net_worth_daily;"
  ```

### Common failures

- A `not_null` or `unique` test failing on `stg_*` tables is almost
  always upstream — a connector inserted a duplicate or NULL key.
  Diagnose with the exact compiled query from `dbt/target/compiled/`,
  then re-ingest.
- `Database Error: relation X does not exist` → migrations were not
  applied (step 1). Re-run `just migrate-up`.

---

## 5. Review numbers — 15 min

Open the Streamlit dashboard:

```bash
uv run --group web --group db penge-web
# → http://localhost:8501
```

(There is no `just web` recipe today.) See [Web dashboard](web.md)
for production deploy options (Tailscale, Caddy basic-auth).

Spot-check, in this order:

1. **Net worth (today + 30 d sparkline).** Compare today's total
   against last month's close (eyeball, ±5 % is normal absent large
   movements). Investigate sudden jumps before continuing.
2. **Cashflow.** The income / expense bars for the closed month
   should be plausible — no missing salary, no impossible negatives.
3. **Per-account drill-down.** Each account's reported balance
   should match the bank's app to the cent. Mismatches mean either a
   missed transaction (re-run step 3 with `--days 60`) or a connector
   bug (file an issue).
4. **Allocation pie.** Stocks / bonds / cash split should not have
   moved by more than the contributions you actually made.
5. **Projection tab** (issue
   [#33](https://github.com/autoditac/Penge/issues/33), see
   [ADR-0022](../decisions/0022-web-projection-dashboard.md)). Run
   the default scenario; the Year-of-FI median should be within ±1 y
   of last month's median absent goal-slider changes.

### What "good" looks like

A short, boring review where every number is explained by activity
the operator already remembers.

### Common failures

- "No data yet" placeholder → marts are empty; step 4 silently
  skipped. Re-run `dbt build` and check its log.
- Account balance mismatches more than one or two days old → the
  PSD2 consent may have rolled over without `authorize`; re-run
  step 3.

---

## 6. Tax preview — 5 min

For the closed month and YTD, eyeball the calculators that exist
today:

```bash
# DK ABIS treatment audit — list any instruments without a sticky
# tax treatment in case Skat moved the list mid-year.
psql "${DATABASE_URL/+psycopg/}" -c "
select isin, name, dk_tax_treatment, dk_tax_treatment_source
from instrument
where dk_tax_treatment is null
order by name;
"
```

The lagerbeskatning, aktiesparekonto, PAL-skat, and
Vorabpauschale calculators are tracked under
[ADR-0017](../decisions/0017-lagerbeskatning-calculator.md),
[ADR-0018](../decisions/0018-aktiesparekonto-handling.md),
[ADR-0019](../decisions/0019-pal-skat-tracking.md) and
[ADR-0021](../decisions/0021-de-vorabpauschale.md). When their CLIs
land they will plug in here as `just tax-preview-dk` /
`just tax-preview-de`. Until then, run the underlying SQL marts and
log the YTD totals into your free-form notes.

### Flag for follow-up

- Any instrument that flipped from `lagerbeskatning` ↔
  `realisation` since last month — record the change in your
  tax log. Domain context: [docs/tax/dk.md](../tax/dk.md),
  [docs/tax/de.md](../tax/de.md).
- Any unusually large gains / dividends that may push the household
  past the next progressionsbracket / Sparer-Pauschbetrag.

---

## 7. Generate report — 5 min

The fully automated PDF + Markdown report is tracked under
[issue #50](https://github.com/autoditac/Penge/issues/50) (Phase 5).
**Until #50 lands**, do a manual capture:

1. Streamlit → "Net worth" tab → screenshot.
2. Streamlit → "Cashflow" tab → screenshot.
3. Streamlit → "Projection" tab (default scenario) → screenshot.
4. Save the three PNGs to:

   ```text
   ~/Nextcloud/Finance/reports/<YYYY-MM>/
   ```

5. Drop a one-page Markdown next to them with: month closed,
   net-worth delta vs. previous month, anomalies you noticed in
   step 5, anything you want to revisit next month.

When #50 ships, this whole step collapses to `just monthly-report`
and the manual capture goes away.

---

## 8. Backup verification — 5 min

```bash
ls -lh "${PENGE_BACKUP_ROOT:-./backups}/postgres" | tail -5
ls -lh "${PENGE_BACKUP_ROOT:-./backups}/duckdb"  | tail -5
```

### What "good" looks like

- A `pg-YYYYMMDDTHHMMSSZ.sql.age` from within the last 24 h, with a
  matching `.sha256` sidecar.
- A `duckdb-…tar.age` from within the last 7 days.

### Quarterly drill (every third monthly ritual — Jan / Apr / Jul / Oct)

```bash
export PENGE_TEST_DATABASE_URL=postgresql://penge:penge@localhost:5432/penge_drill_$(date +%F)
createdb penge_drill_$(date +%F)
just restore-test
```

Then compare row counts on `account`, `transaction`, `instrument`,
`holding` against production, drop the throwaway database, and
record the drill in
[`docs/runbook/restore-log.md`](restore-log.md). Full procedure:
[Encrypted backups → Quarterly restore drill](backup-restore.md#quarterly-restore-drill).
A failed drill is a P1 incident — see ADR-0025.

ADR context:
[ADR-0025 — Encrypted backups](../decisions/0025-encrypted-backups.md).

---

## 9. Close out — minutes

1. If you reclassified anything in the vault by hand or applied a
   sticky ABIS override, commit those changes on a `chore/` branch
   per the [Working Contract](https://github.com/autoditac/Penge/blob/main/AGENTS.md):

   ```bash
   git switch -c chore/$(date +%Y-%m)-monthly-overrides
   git add docs/runbook/restore-log.md  # if you did a drill
   git commit -m "chore: $(date +%Y-%m) monthly ritual overrides"
   gh pr create --fill
   ```

2. Append a short note to your free-form journal (kept outside the
   repo, e.g. `~/Nextcloud/Finance/journal/<YYYY-MM>.md`) with: time
   spent, anomalies, follow-ups, the row counts from the dbt sanity
   query.
3. Close any GitHub issues whose work was completed during the
   ritual.

---

## Time budget recap

| Step | Budget |
| --- | --- |
| 1. Prep | 5 min |
| 2. Vault inbox | 10 min |
| 3. Refresh ingestion | 10 min |
| 4. dbt | 5 min |
| 5. Review numbers | 15 min |
| 6. Tax preview | 5 min |
| 7. Report | 5 min |
| 8. Backup verification | 5 min |
| 9. Close | a few minutes |
| **Total** | **~60 min** |

## Related

- [Vault watcher](vault-watcher.md)
- [Healthchecks: Uptime Kuma + Sentry](healthchecks.md)
- [Encrypted backups](backup-restore.md)
- [Restore drill log](restore-log.md)
- [Web dashboard](web.md)
- [ABIS yearly refresh](abis-yearly-refresh.md)
- [ADR-0003 — Hybrid ingestion](../decisions/0003-hybrid-ingestion-psd2-and-csv-pdf.md)
- [ADR-0022 — Streamlit projection dashboard](../decisions/0022-web-projection-dashboard.md)
- [ADR-0024 — Vault layout](../decisions/0024-vault-layout.md)
- [ADR-0025 — Encrypted backups](../decisions/0025-encrypted-backups.md)
