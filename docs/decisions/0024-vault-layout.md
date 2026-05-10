# 0024 — Document vault layout, hash naming, dedup strategy

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** @autoditac
- **Tags:** vault, infra

## Context and Problem Statement

Penge needs a single, trustworthy place for every financial PDF the
household receives — annual statements, broker reports, payslips,
SKAT/Finanzamt notices, invoices. The source of truth must be:

- **Self-contained on disk** so a Nextcloud sync from any host
  reconstructs full state without a database.
- **Idempotent under retries** so the same file dropped twice never
  produces two copies.
- **Searchable** so a future MCP tool (#44) can grep across years.
- **Observable** so a stalled or crashed watcher is detected before
  documents pile up unprocessed.

Issue #41 ships the inbox watcher + OCR pipeline; this ADR records
the on-disk layout it produces.

## Decision Drivers

- Privacy: the vault holds real bank statements; no cloud OCR.
- Reproducibility: the hash-based naming makes "have I seen this
  file?" answerable from the filename alone.
- Simplicity: a JSON sidecar beats a Postgres table for state that
  must travel with the files.
- Future-proof classification: the rules-based classifier in #42 must
  be able to *re-classify* without re-hashing.

## Considered Options

1. **`vault/{year}/{type}/{sha256}-{slug}.{ext}` + sidecar JSON index** (chosen).
2. `vault/{type}/{year}/...`: type-first hierarchy.
3. Database-only state (Postgres `vault_document` table) with files
   stored under a flat hash-named directory.
4. Content-addressed only: filename = hash, no slug or type folder.

## Decision

We chose **Option 1**: a year-first, type-second hierarchy with full
SHA-256 + slug filenames and a sidecar `.index.json` at the vault root.

Concretely::

    <vault_root>/
        .index.json             # sha256 -> {path, size, filed_at}
        .health                 # heartbeat timestamp (RFC 3339)
        2026/
            unsorted/
                <sha256>-<slug>.pdf
                <sha256>-<slug>.txt   # OCR sidecar
            statements/
                <sha256>-<slug>.pdf
            invoices/
            payslips/
            tax/

- **Year folder = "received-at" year** (UTC). Document-content date is
  often missing or unreliable on first ingest; the rules-based
  classifier (#42) may later infer document date and *move* a file,
  which is cheap because the sha256 in the filename keeps cross-refs
  stable.
- **Type folder = classification bucket.** Until #42 ships, every
  document lands in `unsorted/`. The classifier can move files
  between buckets without rewriting hashes.
- **Filename = `{full sha256}-{slug}.{ext}`.** Full hash makes the
  filename self-describing; the slug derived from the original
  filename keeps the vault browseable. Slug is lowercased,
  non-alphanumeric runs collapse to `-`, capped at 64 chars.
- **OCR sidecar = `{full sha256}-{slug}.txt`** next to the PDF.
  Searchable text extracted by the OCR pipeline is written here so
  `grep`-style search works without re-running Tesseract.
- **Hash dedup** keys on the SHA-256 of the *raw bytes* of the inbox
  file. The sidecar `.index.json` maps `sha256 -> {path, size,
  filed_at}` so the watcher answers "have I seen this?" in O(1)
  without rescanning the tree. The index is *advisory*: if it is
  lost or corrupted, the watcher rebuilds it lazily because every
  filename starts with the canonical hash.

## Consequences

### Positive

- A `find vault -name "<hash>-*"` answers "is this file in the vault?"
  with no DB or index lookup.
- Restoring from a Nextcloud snapshot works: state lives on disk.
- Sidecar `.txt` files make `ripgrep` across years an instant search.
- Year folders keep folder fan-out manageable (≤ a few thousand
  documents per year).

### Negative

- Filenames are long (~80 chars) — fine for ext4/btrfs but a few
  legacy filesystems (FAT32) reject them. Documented in the runbook.
- The slug part is *informational*: tooling must key off the hash
  prefix, not the slug, because the classifier may rename slugs.

### Neutral

- Health surface is a stdlib `http.server` thread serving `/health`
  + `/metrics` (Prometheus text format). Uptime Kuma (#52) hooks
  into either route. We did not add aiohttp/uvicorn — the surface is
  two endpoints with no auth or app logic, and the AGENTS.md
  no-new-deps rule applies. If we ever expose the vault over HTTP
  with real handlers, that ADR should revisit the choice.

## Alternatives in detail

### Type-first (`vault/{type}/{year}/...`)

Cleaner for people who think "all my statements together". Rejected
because (a) the *type* is initially `unsorted` and re-classification
would move large numbers of files across the top of the tree, and
(b) yearly archives are the most common operational unit (e.g. tax
filings; cold-storage backup).

### Database-only state

Stronger consistency and queryability, but breaks the "vault works
even if Postgres is down" property. Reserved for future indexing on
top of the on-disk truth, not as the truth itself.

### Content-addressed only (`vault/{hash}.pdf`)

Cleanest for tooling, but unbrowseable for humans. Rejected on
ergonomics — Penge is operated by two humans, not a fleet.

## Links

- Issue [#41](https://github.com/autoditac/Penge/issues/41) — inbox
  watcher + OCR pipeline.
- Issue [#42](https://github.com/autoditac/Penge/issues/42) — rules-based
  classifier (replaces `unsorted`).
- Issue [#52](https://github.com/autoditac/Penge/issues/52) — Uptime Kuma
  hookup against the `/health` endpoint.
- ADR-0005 — LLM access via MCP only (the future grep tool will hit
  the OCR sidecars, not the PDFs directly).
- Code: `src/penge/vault/`.
