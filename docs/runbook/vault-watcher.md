# Vault inbox watcher

The vault watcher (`penge-vault watch`) tails a Nextcloud-synced
inbox directory and files every incoming PDF into the on-disk vault.
See [ADR-0024](../decisions/0024-vault-layout.md) for the layout and
dedup strategy.

## When

Run continuously on the home server.
The inbox is a Nextcloud-synced folder so any device dropping a PDF
there triggers ingestion within seconds.

## Prerequisites

- Tesseract with the DA + DE + EN language packs installed:

  ```sh
  sudo apt-get install -y tesseract-ocr tesseract-ocr-dan tesseract-ocr-deu tesseract-ocr-eng poppler-utils
  ```

- The inbox + vault directories writable by the running user. The
  watcher creates them on first start.

## Start

```sh
just vault-watch \
    --health-port 9101 \
    ~/Nextcloud/Finance/inbox ~/Nextcloud/Finance/vault
```

The `--health-port` is the Prometheus / Uptime Kuma scrape target
(see issue #52). `0` (the default) binds an ephemeral port and prints
it on startup.

## Drain once (no watch loop)

Useful for cron, CI, and manual catch-up runs:

```sh
just vault-watch --once ~/Nextcloud/Finance/inbox ~/Nextcloud/Finance/vault
```

## What to watch

- **Heartbeat file**: `<vault_root>/.health` — its mtime bumps on each
  scan tick. If it goes older than ~2× `--scan-interval`, the watcher
  is stuck and should be restarted.
- **`/health` endpoint**: returns the heartbeat timestamp on `200 OK`,
  `503 starting` if the watcher has not yet beaten once.
- **`/metrics` endpoint**: Prometheus text-format metrics. Useful keys:
  - `vault_files_seen_total` — every file the worker pulled.
  - `vault_files_filed_total` — successfully OCR'd + filed.
  - `vault_duplicates_total` — dropped because hash already on file.
  - `vault_failures_total` — OCR or filer errors. Should be `0`.
  - `vault_index_size` — number of unique documents in the vault.

## Recovering from a crash

The vault is *self-healing*: the on-disk filenames carry the canonical
SHA-256 prefix, so a corrupted `.index.json` can be reconstructed by
walking the tree. If you suspect drift:

1. Stop the watcher.
2. Move `<vault_root>/.index.json` aside.
3. Restart the watcher with `--once` against an empty inbox to
   regenerate `.health`.
4. The first real drop will repopulate the index lazily.

A future runbook (#42) will ship a one-shot `penge-vault rebuild-index`
helper.

## What stays in the inbox

Files with unsupported suffixes (anything other than `.pdf`) are
**left in place** and a warning is logged. The OCR pipeline is
PDF-only today; image-only inputs (`.jpg`, `.png`) are deferred to a
future iteration.
