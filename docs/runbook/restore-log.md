# Restore drill log

Operators record every quarterly restore drill (and any ad-hoc restore)
here so we have an audit trail proving the encrypted-backup pipeline
actually round-trips. See
[`docs/runbook/backup-restore.md`](backup-restore.md) for the drill
procedure and [ADR-0025](../decisions/0025-encrypted-backups.md) for
context.

## Template

Copy the block below to the top of the table when recording a new
drill. Keep entries newest-first.

| Date (UTC) | Operator | Artefact | Restore target | Row counts match? | Notes |
|------------|----------|----------|----------------|-------------------|-------|
| YYYY-MM-DD | @handle  | `pg-YYYYMMDDTHHMMSSZ.sql.age` | `penge_restore_smoke` | ✅ / ❌ | free-form |

## Log

<!-- Add entries above this line, newest first. -->

| Date (UTC) | Operator | Artefact | Restore target | Row counts match? | Notes |
|------------|----------|----------|----------------|-------------------|-------|
| _no drills recorded yet_ | | | | | |
