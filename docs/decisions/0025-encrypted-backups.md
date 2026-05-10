# 0025 — Encrypted backups: age + Parquet snapshots

- **Status:** Proposed
- **Date:** 2026-05-08
- **Deciders:** @autoditac
- **Tags:** infra, security

## Context and Problem Statement

Penge holds DK and DE financial data: balances, transactions, holdings,
tax lots, and PDF statements stored under the vault tree (ADR-0024).
Loss of the Postgres database (disk failure on the home server,
mistaken `DROP TABLE`, ransomware, hardware theft) would either erase
years of reconciled history or — worse — leak it if the backup
pipeline puts plaintext on a disk we don't fully control.

We need a backup pipeline that is:

1. **Encrypted at rest, end-to-end.** A backup file on a USB drive in
   the safe, an off-site Hetzner Storage Box, or an old laptop must
   be useless to a finder without the matching private key.
2. **Restorable in a fire drill.** The operator must be able to
   reproduce a working database from nothing more than the encrypted
   artefact and an offline private key.
3. **Auditable.** Every artefact carries a timestamp, an integrity
   hash, and a deterministic filename so retention pruning is safe.
4. **Boring.** No bespoke crypto, no key servers, no dependency on a
   cloud KMS we don't already pay for.

## Decision Drivers

- **Threat model.** Adversaries we plan for: a thief who steals the
  home server or its USB backup drive; a misbehaving cloud provider
  that reads our object-store contents; a future Penge developer who
  pulls the wrong tarball onto a shared workstation. Adversaries we
  do **not** plan for in v1: a state-level attacker with persistent
  on-host access; a coerced custodian.
- **Key custody.** We want the private key offline (printed paper +
  encrypted USB stick in a safe) plus on each operator device that
  needs to decrypt. No cloud copies.
- **Operator ergonomics.** The operator runs Linux + macOS at home
  and wants a `just backup` / `just restore-test` flow, not a five-
  step GnuPG ritual.
- **Reproducibility.** Backups must be exactly reproducible from the
  encrypted artefact alone — no out-of-band metadata required to
  decrypt.

## Considered Options

1. **`age` (pinentry-free, modern).** Curve25519 + ChaCha20-Poly1305,
   one tiny binary, X25519 recipients, simple `-r <pubkey>` CLI, no
   keyrings.
2. **GnuPG.** Battle-tested, ubiquitous on Linux. Heavyweight
   (keyrings, agents, web-of-trust), legendary configuration foot-
   guns, awkward to script for non-interactive backups.
3. **Cloud KMS-wrapped envelopes (AWS KMS, GCP KMS, Hashicorp Vault).**
   Strong access control on paper. Adds a hard dependency on a
   third-party service to decrypt — exactly the property that ruins
   day-7 disaster recovery.
4. **Postgres native pgBackRest with TDE.** Excellent for managed
   fleets; overkill for a single-host home server, and pulls in a
   stateful backup repository service we'd then need to back up too.

## Decision

We use **`age`** (Option 1) with one or more X25519 recipient public
keys configured via `PENGE_BACKUP_RECIPIENTS`. Postgres backups are
plain `pg_dump` output piped through `age`; DuckDB snapshots are
per-table Parquet files packed in a tar stream and piped through
`age`. The `age` private key (`age-keygen` output) lives in two places:

- A printed copy in the safe (page is small enough to fit on A4).
- An encrypted USB stick in the same safe.

For routine restores the operator copies the identity file onto the
machine that needs it (`PENGE_BACKUP_IDENTITY_FILE`) and removes it
afterwards. Operator workstations may keep the identity file under
`~/.config/penge/` with mode `0600` for convenience.

### Pipeline

```text
pg_dump --format=plain --no-owner --no-privileges
   │
   ▼
age -r <pubkey> [-r <pubkey>...]
   │
   ▼
backups/postgres/pg-YYYYMMDDTHHMMSSZ.sql.age   (+ .sha256 sidecar)
```

The DuckDB path is symmetric:

```text
duckdb COPY ... TO 'tbl.parquet' (FORMAT PARQUET)   (per table, in a scratch dir)
   │
   ▼  (tar stream of {manifest.tsv, *.parquet})
   │
   ▼
age -r <pubkey> [-r <pubkey>...]
   │
   ▼
backups/duckdb/duckdb-YYYYMMDDTHHMMSSZ.tar.age   (+ .sha256 sidecar)
```

The unencrypted dump never lands on disk: pg_dump writes to the pipe,
age writes the ciphertext directly to the destination file. The
DuckDB scratch directory lives under the backup root (never `/tmp`)
and is deleted on every exit path via a `trap`.

### Retention

`scripts/prune.sh` keeps **14 daily** + **8 weekly** + **12 monthly**
artefacts by default. The defaults are configurable per invocation
(`--daily`, `--weekly`, `--monthly`) and via env
(`PENGE_BACKUP_RETENTION_*`). Buckets are derived from the timestamp
embedded in the filename, not file mtime, so syncing artefacts across
hosts doesn't reshuffle the policy.

### Restore drill cadence

We exercise restore quarterly (Q1 / Q2 / Q3 / Q4 — first weekend of
the quarter):

1. Decrypt the most recent `pg-*.sql.age` into a throwaway database.
2. Run a `pg_dump --schema-only` diff against the live database.
3. Compare row counts on the headline tables (`account`,
   `transaction`, `instrument`, `holding`).

CI runs the same round-trip (`.github/workflows/backup-roundtrip.yml`)
on every PR that touches `scripts/**`, so the script-level invariant
is continuously tested.

### Key rotation

Rotation is straightforward because `age` recipients are independent
public keys, not a keyring with a web of trust:

1. `age-keygen -o new-identity.txt` → publish the new public key.
2. Add the new public key to `PENGE_BACKUP_RECIPIENTS` next to the
   existing one (comma-separated). New artefacts are now decryptable
   by **either** key.
3. Run a manual `just backup` and verify a restore drill against the
   new key.
4. After 90 days, remove the old public key from
   `PENGE_BACKUP_RECIPIENTS`. The old key still decrypts artefacts
   from before the rotation; new artefacts cannot.
5. Securely destroy the old private-key paper and wipe the old USB
   stick (single overwrite + physical destruction is sufficient
   given the threat model).

We **never** re-encrypt historical artefacts. If an old key is
compromised, that breach exposes whatever data is in the artefacts
that key encrypted — and the appropriate response is to assume that
window of history is leaked, not to attempt to scrub the artefacts.

## Consequences

### Positive

- One small binary (`age`) on every host that takes or restores
  backups; no keyrings, no agents, no daemons.
- Multiple recipients are first-class: rotation and shared access
  (e.g. spouse) just work.
- Encrypted artefacts are self-contained — restorable on a fresh
  laptop with nothing but `age`, `psql`/`duckdb`, and the identity
  file from the safe.
- The `.sha256` sidecar lets the operator detect bit-rot before
  attempting a restore on cold storage.

### Negative

- `age` is younger than GnuPG and has a smaller pool of public
  cryptographic review. We mitigate by pinning the package version
  and tracking [the `age` advisory feed](https://github.com/FiloSottile/age/security/advisories).
- Plain SQL dumps are larger than custom-format dumps. Restore is
  also single-threaded (`psql -f -`) compared to `pg_restore --jobs`.
  At Penge's data volume (10⁵–10⁶ rows) this is a non-issue; if it
  becomes one we switch to `--format=custom`, which is a one-line
  change in `scripts/backup.sh`.
- Compromise of the on-device identity file exposes all artefacts
  that recipient could decrypt. Mitigated by file mode `0600`,
  full-disk encryption on the host, and the rotation procedure above.

### Neutral

- Postgres backups are logical (`pg_dump`) rather than physical
  (PITR). Penge has no SLO for sub-day RPO, and logical backups are
  trivially portable across major Postgres versions, which fits the
  home-server upgrade cadence.

## Alternatives in detail

### Option 2 — GnuPG

GnuPG would also work, but the operational surface is hostile:
keyrings carry per-host state, `gpg-agent` interferes with
non-interactive cron jobs, and the Web-of-Trust UX is irrelevant
to a single-operator threat model. The
[*age* design notes](https://age-encryption.org/) explicitly target
this gap.

### Option 3 — Cloud KMS

A KMS-wrapped envelope ties our disaster-recovery path to a vendor
account. The first thing we'd want during an actual disaster (a
fresh laptop on a flaky hotel Wi-Fi) is to **not** depend on cloud
auth.

### Option 4 — pgBackRest

pgBackRest is the right answer for a fleet of managed Postgres
instances. For one home server it adds a stateful repository service
that itself needs encryption, retention, and monitoring — pushing the
problem one level down without solving it.

## Links

- `scripts/backup.sh`
- `scripts/snapshot.sh`
- `scripts/restore.sh`
- `scripts/prune.sh`
- [`docs/runbook/backup-restore.md`](../runbook/backup-restore.md)
- `.github/workflows/backup-roundtrip.yml`
- [age — A simple, modern and secure encryption tool](https://age-encryption.org/)
- ADR-0001 — Self-hosted Postgres + DuckDB stack
- ADR-0024 — Vault layout
