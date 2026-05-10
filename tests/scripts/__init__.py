"""Tests for the encrypted-backup shell scripts.

These tests shell out to ``scripts/backup.sh`` / ``snapshot.sh`` /
``restore.sh`` / ``prune.sh`` and rely on real ``age`` and (for the
Postgres round-trip) ``pg_dump``/``psql`` binaries. They are the same
scripts the operator runs by hand and the same ones that
``.github/workflows/backup-roundtrip.yml`` exercises in CI.

Where a binary is missing the relevant test is skipped; the
``test_prune_*`` battery is pure bash + GNU date and always runs.
"""
