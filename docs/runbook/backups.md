# Encrypted backups

Penge's backup pipeline is a pair of shell scripts under
[`scripts/`](https://github.com/autoditac/Penge/tree/main/scripts) that
encrypt every artefact with [age](https://age-encryption.org/) before
it touches disk. See [ADR-0025](../decisions/0025-encrypted-backups.md)
for the design and threat model.

## Prerequisites

Install the binaries on every host that takes or restores backups:

```bash
# Debian / Ubuntu
sudo apt-get install -y age postgresql-client

# macOS
brew install age libpq
```

The DuckDB CLI is published as a single static binary on the
[duckdb/duckdb releases page](https://github.com/duckdb/duckdb/releases);
download, verify the SHA-256, and install to `/usr/local/bin/duckdb`.

Generate a key-pair once and stash the identity file as ADR-0025
describes:

```bash
age-keygen -o ~/.config/penge/identity.txt
chmod 600 ~/.config/penge/identity.txt

# The public key is printed on stderr by age-keygen and embedded as a
# comment at the top of the identity file.
grep '^# public key:' ~/.config/penge/identity.txt
```

Distribute the **public key** to every host that takes backups; keep
the private key offline (printed in the safe + encrypted USB stick).

## Configuration

The scripts are configured via environment variables:

| Variable                          | Required | Description                                                          |
| --------------------------------- | -------- | -------------------------------------------------------------------- |
| `PENGE_BACKUP_RECIPIENTS`         | one of   | Comma-separated list of `age` public keys.                           |
| `PENGE_BACKUP_RECIPIENTS_FILE`    | one of   | Path to a file with one recipient per line (`#` comments allowed).   |
| `PENGE_BACKUP_IDENTITY_FILE`      | restore  | Path to an `age-keygen` identity file (mode `0600`).                 |
| `PENGE_BACKUP_ROOT`               | no       | Backup root. Defaults to `./backups` (gitignored).                   |
| `DATABASE_URL`                    | backup   | Postgres URL (libpq or SQLAlchemy form).                             |
| `PENGE_BACKUP_RETENTION_DAILY`    | no       | Override default `--daily 14`.                                       |
| `PENGE_BACKUP_RETENTION_WEEKLY`   | no       | Override default `--weekly 8`.                                       |
| `PENGE_BACKUP_RETENTION_MONTHLY`  | no       | Override default `--monthly 12`.                                     |

Set them in `.env` (gitignored) or your shell profile. **Never commit
recipients or identity files.**

## Daily operations

```bash
# Postgres logical backup (pg_dump | age)
just backup

# DuckDB → Parquet snapshot (per-table COPY | tar | age)
just snapshot DUCKDB=./data/penge.duckdb

# Round-trip restore drill (decrypt + replay into a throwaway DB).
# Uses PENGE_TEST_DATABASE_URL; never points at production.
just restore-test

# Apply retention (14 daily / 8 weekly / 12 monthly by default)
just backup-prune
```

Each artefact is written as `pg-YYYYMMDDTHHMMSSZ.sql.age` (or
`duckdb-YYYYMMDDTHHMMSSZ.tar.age`) alongside a `.sha256` sidecar that
the restore script verifies before decrypting.

## Manual invocation

The Just recipes are thin wrappers; call the scripts directly when you
want flags:

```bash
./scripts/backup.sh --label pre-upgrade
./scripts/snapshot.sh --duckdb ./data/penge.duckdb --label pre-upgrade
./scripts/restore.sh \
    --input ./backups/postgres/pg-20260508T034500Z-pre-upgrade.sql.age \
    --database-url postgresql://penge:penge@localhost:5432/penge_restore_drill \
    --identity ~/.config/penge/identity.txt
./scripts/prune.sh --root ./backups --daily 30 --weekly 12 --monthly 24
```

## Scheduling

We do **not** ship a packaged unit file or cron job — the home server
already runs scheduling, and a generic example is portable enough.

### Linux (systemd timer)

```ini
# /etc/systemd/system/penge-backup.service
[Unit]
Description=Penge encrypted Postgres backup
After=network-online.target postgresql.service

[Service]
Type=oneshot
User=penge
EnvironmentFile=/etc/penge/backup.env
WorkingDirectory=/srv/penge
ExecStart=/srv/penge/scripts/backup.sh
ExecStartPost=/srv/penge/scripts/prune.sh
```

```ini
# /etc/systemd/system/penge-backup.timer
[Unit]
Description=Run penge-backup nightly

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true
RandomizedDelaySec=15m

[Install]
WantedBy=timers.target
```

`/etc/penge/backup.env` (mode `0600`) sets `PENGE_BACKUP_RECIPIENTS`,
`PENGE_BACKUP_ROOT`, and `DATABASE_URL`. Enable with:

```bash
systemctl enable --now penge-backup.timer
systemctl list-timers penge-backup.timer
```

### Cron

```cron
# /etc/cron.d/penge-backup
30 3 * * *  penge  cd /srv/penge && ./scripts/backup.sh && ./scripts/prune.sh
```

Cron's environment is empty — keep the env file referenced via a shim
or pass values inline.

## Quarterly restore drill

ADR-0025 commits us to a quarterly drill. The procedure:

1. Pick the most recent `pg-*.sql.age`.
2. Provision a throwaway database (`createdb penge_drill_$(date +%F)`).
3. Run `scripts/restore.sh --input ... --database-url ...`.
4. Compare row counts on the headline tables against production:

   ```sql
   SELECT 'account' AS t, count(*) FROM account UNION ALL
   SELECT 'transaction',     count(*) FROM transaction UNION ALL
   SELECT 'instrument',      count(*) FROM instrument UNION ALL
   SELECT 'holding',         count(*) FROM holding;
   ```

5. Drop the throwaway database.
6. Record the drill in `docs/runbook/restore-log.md` (date, artefact
   timestamp, observed deltas).

A failed drill is a P1 incident: every backup taken since the last
successful drill is suspect.

## Troubleshooting

| Symptom                                                              | Likely cause                                                                                |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `no age recipients configured`                                       | `PENGE_BACKUP_RECIPIENTS` / `PENGE_BACKUP_RECIPIENTS_FILE` not exported.                    |
| `sha256 mismatch for ...`                                            | Artefact bit-rot or partial download. Refetch from another mirror; do **not** `--skip-hash-check` blindly. |
| `pg_restore: error: connection to server ... FATAL`                  | Wrong `--database-url`, or the target database doesn't exist yet.                           |
| `decrypted nothing — empty stream`                                   | Wrong identity file. Remember `age` doesn't tell you which recipient encrypted the artefact. |

## Related

- [ADR-0025 — Encrypted backups: age + Parquet snapshots](../decisions/0025-encrypted-backups.md)
- [`scripts/backup.sh`](https://github.com/autoditac/Penge/blob/main/scripts/backup.sh)
- [`scripts/snapshot.sh`](https://github.com/autoditac/Penge/blob/main/scripts/snapshot.sh)
- [`scripts/restore.sh`](https://github.com/autoditac/Penge/blob/main/scripts/restore.sh)
- [`scripts/prune.sh`](https://github.com/autoditac/Penge/blob/main/scripts/prune.sh)
- [`.github/workflows/backup-roundtrip.yml`](https://github.com/autoditac/Penge/blob/main/.github/workflows/backup-roundtrip.yml)
