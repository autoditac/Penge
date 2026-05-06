---
applyTo: "docs/**"
---

# Documentation instructions

## Stack

- Docs are built with **MkDocs Material** and deployed to GitHub Pages on tag.
- Diagrams are **Mermaid** (rendered by MkDocs Material) or **Structurizr-lite** for C4 diagrams.
- Architecture Decision Records use the **MADR** template in `docs/decisions/`.

## Layout

```
docs/
  index.md
  architecture/        # C4 + sequence diagrams
  runbook/             # operational procedures
  connectors/          # one page per data source
  tax/
    dk.md              # DK rules used by the tax engine
    de.md              # DE rules used by the tax engine
  decisions/
    README.md
    adr-template.md
    0001-*.md
    ...
```

## Style

- Markdown formatted with `prettier` and linted with `markdownlint`.
- One sentence per line in long-form prose where possible (eases diff review).
- Headings use ATX style (`#`, `##`, ...).
- Code blocks must specify a language.
- Cross-link generously: every concept reference links to its definition page.

## Architecture Decision Records (ADRs)

- Filename: `NNNN-kebab-case-title.md`, sequential, never reused.
- Status flow: `Proposed` → `Accepted` (on PR merge) → `Deprecated` / `Superseded by ADR-XXXX`.
- An ADR is required for any of the following changes:
  - Adding/replacing a service, library, or external dependency.
  - Changing the data model (table, column, fact/dim).
  - Changing a tax-rule interpretation.
  - Changing an integration pattern.
  - Changing a security or privacy boundary.
- ADRs are short (½–2 pages). Decision rationale is the important part.

## Connector docs

Each connector under `apps/ingest/connectors/` has a corresponding page in `docs/connectors/<source>.md` covering:

- What this source provides (transactions? holdings? prices?).
- How to authenticate / obtain credentials.
- Refresh cadence and rate limits.
- Known data quirks and how the parser handles them.
- Schema mapping table (source field → canonical field).
- Manual fallback procedure when the source is down.

## Runbook

- `docs/runbook/monthly.md` — the 1-hour monthly ritual.
- `docs/runbook/incident.md` — what to do when ingestion breaks.
- `docs/runbook/backup-restore.md` — recovery procedure.
- `docs/runbook/tax-year-close.md` — yearly tax-prep procedure.

## Languages

Pages are English by default. German pages are suffixed `.de.md` and linked from the English page.
