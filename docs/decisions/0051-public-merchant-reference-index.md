# ADR-0051 — Versioned public merchant reference index

- **Status:** Proposed
- **Date:** 2026-10-03
- **Deciders:** @autoditac
- **Tags:** ingest, security, privacy, web

## Context and Problem Statement

Household merchant identities and aliases are private, locally curated data.
Public merchant suggestions can improve local matching, but external lookups
must never reveal transaction descriptions, payees, amounts, account IDs, or
household-specific selections.
The public index also needs explicit provenance and failure status, and source
refreshes must not replace a previously validated index with partial or invalid
data.

## Decision Drivers

- Keep all transaction and household-specific matching local.
- Use a versioned public catalog with explicit license and provenance.
- Bound all network payloads and validate a whole snapshot before promotion.
- Preserve local identities, aliases, and category decisions independently.
- Treat source business-type hints as suggestions, never household expense
  classifications.
- Keep refresh behavior deterministic and auditable.

## Considered Options

1. **Wikidata Query Service snapshot queries** — query broad brand/company
   classes and page through public entities.
2. **Name Suggestion Index (NSI) published catalog** — consume an exact-version
   compiled brand catalog and validate its package integrity.
3. **OpenStreetMap API or planet extracts** — query or download raw map data
   and derive merchant references.

## Decision

The user explicitly approved this NSI source choice instead of the initial
Wikidata direction on 2026-10-03, including the BSD-3-Clause notice, upstream
OpenStreetMap attribution, and local-only private matching requirements.
The ADR remains Proposed until the implementation is reviewed and merged.

Use the compiled NSI catalog from its officially published npm package.
Discover the release through the official npm registry, then fetch only the
exact versioned tarball from the allowlisted registry host.
Verify the registry-published SHA-512 integrity, embedded package metadata,
BSD 3-Clause notice, catalog version, catalog URL, and complete catalog shape
before a new generation can become active.
The registry-provided digest verifies consistency with npm's metadata; it is
not an independent publisher signature. Release discovery therefore relies on
the official registry over HTTPS, and the chosen version and checksums are
recorded locally.
The scheduled refresh checks for a new version daily and skips the large
catalog download when the active version is unchanged.

Only catalog records under `brands/` are imported.
Penge treats the catalog's name variants as literal strings and does not run
its matching or exclusion expressions.
Catalog category paths are public source hints only; they do not assign
household expense categories.
The local matcher preserves duplicate public names as distinct references and
does not automatically create or alter a household merchant.

The NSI project's README says its catalog is collected manually and through
the NSI Collector's OpenStreetMap planet scan.
The published NSI package identifies its catalog as BSD 3-Clause licensed.
Penge preserves the full BSD notice and acknowledges OpenStreetMap's separate
ODbL copyright/attribution page.
Penge downloads no raw OSM features and does not combine public reference data
with private household transaction or alias tables.
This decision does not claim that the NSI package changes the license of
underlying OpenStreetMap data.

## Consequences

### Positive

- A complete published catalog is available in one bounded, versioned
  snapshot, without a crawler over unrelated Wikidata entities.
- The catalog has useful DK and DE examples, including 365discount aliases in
  Denmark and region-specific Aldi entries.
- Package integrity, source version, checksum, and generation timestamps can
  be recorded with every promoted index.
- Failed, incomplete, or invalid downloads leave the last validated generation
  active and expose an explicit stale/error state.
- Public data remains separate from private merchant aliases and manual
  classifications.

### Negative

- NSI coverage is community-maintained, incomplete, and not a full merchant
  directory.
- Some NSI aliases or feature-type hints may be inappropriate for transaction
  matching; literal exact matching and ambiguity handling are required.
- A daily release check depends on the npm registry, while new package releases
  may occur less frequently.
- Because NSI describes planet scans as one input, this ADR acknowledges OSM's
  ODbL attribution requirements without making a legal determination about
  every upstream record's provenance.

### Neutral

- The catalog is downloaded only when the package version changes.
- Wikidata QIDs are retained when the NSI record provides them, but Penge does
  not make household-specific Wikidata queries.
- OSM location sets are not interpreted as a complete geographic model.

## Alternatives in detail

### Wikidata Query Service snapshot queries

Simple public queries confirmed the `schema:dateModified` property and a
limited class/QID query shape.
The full broad query needed for entity labels and aliases timed out during a
bounded two-row public test.
An all-pages entity crawl would traverse many millions of unrelated Wikidata
entities.
Neither query path provides a suitable, efficiently complete merchant
snapshot for this feature.

### OpenStreetMap API or planet extracts

Raw OSM queries and planet extracts would require a separate, broader
ODbL/attribution and API-usage review, and the feature does not need raw
geographic observations.
Penge therefore does not use either source directly.
The chosen source is the NSI project's separately published catalog, with its
own BSD 3-Clause notice and its OSM provenance acknowledged.

## Links

- [NSI project](https://github.com/osmlab/name-suggestion-index)
- [NSI 8.0.20260918 package](https://www.npmjs.com/package/name-suggestion-index/v/8.0.20260918)
- [NSI BSD 3-Clause license](../licenses/name-suggestion-index.md)
- [OpenStreetMap copyright and license](https://www.openstreetmap.org/copyright)
- [OpenStreetMap ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/)
- [Household categorization foundation (#330)](https://github.com/autoditac/Penge/issues/330)
