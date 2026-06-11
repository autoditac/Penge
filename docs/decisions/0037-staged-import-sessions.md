# 0037 — Staged import sessions behind the FastAPI app

- **Status:** Proposed
- **Date:** 2026-06-13
- **Deciders:** @autoditac
- **Tags:** api, ingest, web, security, data

## Context and Problem Statement

Every statement import today is a CLI run (`penge-nordnet`, `penge-growney`,
`penge-pfa`, `penge-manual`) that parses a file and writes straight into the
raw tables. There is no way to *see* what a file contains before it lands in
Postgres, no way to fix a single bad row without editing the source file, and
no surface the upcoming import wizard UI (issue #208) can talk to.

Issue #207 asks for staged import sessions: upload a file, review parsed rows
with validation and duplicate flags, correct individual rows, and only then
commit — writing the raw tables exactly as the CLI ingest would.

## Decision Drivers

- **Nothing touches the raw tables until commit.** Review must be safe.
- **Commit must reuse the existing loaders** (`load_records`), not duplicate
  upsert logic; CLI and API imports must produce identical rows.
- **ADR-0035 made the read API read-only by design** (`postgresql_readonly`
  on every connection). That posture must survive this change.
- Uploaded statements are sensitive: they must stay under the gitignored
  `data/` tree, be size-capped, and never appear in logs.
- The session/row state must be durable and auditable (a database, not
  process memory), and migrations must stay reversible.

## Considered Options

1. **Staging tables (`import_session` / `import_row`) + a scoped write
   engine inside the existing FastAPI app** — parsed rows persisted as
   JSONB, commit re-validates through the parser models and calls the
   loaders' `load_records`.
2. **In-memory sessions in the API process** — no migration, but state dies
   on restart, cannot be audited, and breaks with more than one worker.
3. **A separate "import service" process** — clean write/read split at the
   process level, but a second deployment unit, second CORS surface, and
   second auth story for a single-household tool.
4. **Commit by shelling out to the CLI entrypoints** — maximum reuse on
   paper, but loses typed row corrections (the CLI only accepts files) and
   makes error mapping to HTTP responses brittle.

## Decision Outcome

Chosen option: **(1) staging tables + a scoped write engine**.

### Architecture

- New subpackage `penge.api.imports` containing everything write-related;
  the existing route/data modules stay read-only.
- `get_import_engine()` is a second, lazily created engine **without**
  `postgresql_readonly`. Only the imports router uses it. The read-only
  default from ADR-0035 stays the rule; this module is the documented,
  reviewable exception.
- Two new tables (Alembic migration `0004`, reversible):
  - `import_session` — id, source, original filename, SHA-256, stored path,
    status (`staged | committed | discarded | expired`), commit parameters
    (JSONB), error text, created/updated/expires/committed timestamps.
  - `import_row` — id, session FK (cascade delete), row index, row kind,
    payload (JSONB dump of the parsed Pydantic record), status
    (`ok | warning | error`), issues (JSONB list), `edited`, `excluded`.
- Sources v1 (one uploaded file per session):
  `nordnet_transactions`, `growney`, `pfa`, and `manual_balances` (a small
  JSON list of balance entries so manual numbers get the same
  review-then-commit path; committed via
  `penge.manual.service.record_cash_balance`).
  Nordnet *holdings* CSVs are explicitly out: the loader resolves
  instruments through the transaction history, so a holdings-only load
  silently skips unmapped positions. Holdings stay on the CLI path (both
  files in one run) until sessions support multi-file uploads (#208).
- Source auto-detection sniffs filename + content (UTF-16 Nordnet headers,
  PDF magic + provider keywords, JSON shape); an explicit `source` form
  field always wins. Undetectable files are rejected with 422.
- Duplicate detection happens at staging time: for transaction rows the
  staged external id is checked against `transaction` /
  `ux_transaction__account_id_external_id` (the same key the loaders' ON
  CONFLICT upserts use). Duplicates become `warning` rows, never blockers —
  committing them is an idempotent upsert by construction.
- `PATCH …/rows/{id}` re-validates the corrected payload through the same
  parser model and recomputes flags; rows can also be excluded from commit.
- `POST …/commit` re-validates every included row, calls the loader's
  `load_records` (one transaction; failure rolls back and the session stays
  staged), then marks the session committed. Committed/discarded sessions
  keep their rows for audit.
- Sessions expire (default 7 days, `PENGE_IMPORT_SESSION_TTL_DAYS`).
  Expiry is enforced lazily on access; a Just recipe documents cleanup.

### Upload handling

- Multipart parsing needs `python-multipart`; FastAPI has no built-in
  multipart parser and no existing dependency provides one, so it is added
  to the `api` group (pinned like the rest).
- Files stream to `PENGE_IMPORT_DIR` (default `data/imports/<session-id>/`)
  in chunks with a hard size cap (`PENGE_IMPORT_MAX_BYTES`, default 25 MiB
  → 413). The original filename is preserved (sanitised) because the
  Nordnet holdings parser derives account number and as-of date from it.
- Logs carry session ids, sizes, and row counts — never file contents.

### Consequences

- Good: review-before-write imports; one shared write path with the CLI;
  the wizard UI (#208) gets a complete REST surface.
- Good: the read-only invariant stays machine-enforced everywhere except
  one explicitly scoped module.
- Bad: the API container now needs write credentials when imports are
  enabled; mitigated by keeping the API local-only (127.0.0.1 binding,
  ADR-0035) and by the single scoped engine.
- Bad: staged payloads duplicate file content into Postgres as JSONB;
  acceptable for statement-sized files (size cap) and required for row
  corrections and audit.

## Links

- Issue #207 — staged import sessions
- [ADR-0035](0035-fastapi-read-api.md) — read-only API posture
- [ADR-0005](0005-llm-access-via-mcp-only.md) — MCP-only LLM data path
- Follow-ups: #208 (import wizard UI), #209/#210 (AI mapping suggestions)
