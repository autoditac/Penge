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
  - `vault_unclassified_total` — documents filed under `unsorted/`
    because no classifier rule fired above the configured threshold.
    See the "Document classifier" section below.
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

## Document classifier

After OCR, every document runs through a rule-based classifier
(`penge.vault.classifier`) that picks one of:

`lønseddel`, `gehaltsabrechnung`, `årsopgørelse`, `steuerbescheid`,
`kontoauszug`, `depotauszug`, `pfa-statement`, `hypothek`,
`grundbuch`, `versicherungspolice`, `unsorted` (fallback).

The chosen category becomes the second path component of the filed
document (`vault/{year}/{category}/{hash}-{slug}.pdf`).

### How it works

- Patterns live in `config/vault-classifier.yaml`.
- Each category lists regex patterns matched (case-insensitive)
  against the lowercased OCR text.
- A document scores `matches / total_patterns` per category; the
  highest-scoring category above `min_confidence` wins.
- Sub-threshold documents file under `unsorted/`, emit a structured
  `vault.classifier.unclassified` warning, and bump the
  `vault_unclassified_total` Prometheus counter (visible on
  `/metrics`).

### Tuning the rules

1. Edit `config/vault-classifier.yaml`. Add language-aware tokens
   (DA / DE / EN) and keep patterns *anchored* (`\\b…\\b`) and
   document-distinctive — generic words like "saldo" appear on
   many statement types and dilute precision.
2. Tighten/loosen the threshold via `min_confidence`. Default
   `0.33` requires roughly two of six patterns to fire.
3. Re-run the confusion-matrix test:

   ```sh
   uv run --group vault --group parsers pytest tests/vault/test_classifier.py -v
   ```

   On failure the test prints the full confusion matrix plus a
   per-fixture prediction list to make tuning actionable.
4. To add a fresh labeled fixture, extend `LABELED_SAMPLES` in
   `tools/generate_vault_fixtures.py`
   and re-run it (`uv run --group parsers python tools/generate_vault_fixtures.py`).
   Synthetic fixtures only — never copy a real statement into the
   repo.

### Manual triage of `unsorted/`

When `vault_unclassified_total` increments (Uptime Kuma alert
candidate), inspect `vault/{year}/unsorted/`, decide the correct
category, and either:

- file a PR adding/strengthening rules in `vault-classifier.yaml`,
  then re-run the watcher with `--once` to refile, or
- manually move the file into the correct `vault/{year}/<category>/`
  folder (the `.index.json` carries the SHA, so the watcher will not
  re-ingest it).
