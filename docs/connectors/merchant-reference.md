# Public merchant reference index

Penge refreshes a local public reference index from the compiled
[Name Suggestion Index (NSI)](https://github.com/osmlab/name-suggestion-index).
The source contains canonical brand names, literal alternate names, Wikidata
identifiers where available, and OpenStreetMap feature-type hints.

## Source and provenance

The refresh discovers the published `name-suggestion-index` package version
through the official npm registry, then downloads only that exact version's
compiled catalog.
The package archive and catalog are bounded, validated, and checksummed before
the candidate index can replace the last validated generation.
The running application does not install or execute the NSI package.
The registry integrity digest detects whether the downloaded tarball matches
the registry metadata; the metadata and digest are not a publisher signature.
Penge trusts the configured HTTPS connection to the official npm registry for
release discovery and records the validated version and checksums for audit.

The project README describes the catalog as manually curated and collected via
the NSI Collector's planet scan.
The package publishes its catalog under the BSD 3-Clause license.
Penge records the release version, catalog checksum, upstream entity ID,
catalog generation time, retrieval time, source URL, and license.
See the [NSI license notice](../licenses/name-suggestion-index.md).

Penge consumes the published catalog only; it does not fetch or store raw
OpenStreetMap features.
The catalog's NSI provenance and BSD notice are preserved, and the NSI source's
OpenStreetMap connection is acknowledged below.
This documentation does not claim that the BSD license replaces or changes
the Open Database License (ODbL) for any underlying OpenStreetMap data.

## Data use and limits

The index is public reference data kept separate from household transactions,
private aliases, manual merchant identities, and expense-category rules.
Refresh requests contain only public package names and version identifiers.
Transaction descriptions, payees, amounts, account IDs, and household-specific
vendor selections are never sent to NSI, Wikidata, or another matching service.

NSI feature categories are source hints, not household spending categories.
They must not assign or change a household expense category.
Aliases are treated as literal strings; NSI matching or exclusion expressions
are not executed.
Duplicate names remain separate public references so local matching can treat
collisions as ambiguous instead of merging identities.
Processor, marketplace, and mixed-identity entries are suggestions only and
must not create a default household merchant or expense category.
Coverage is incomplete and may vary by region or release.

The catalog's `locationSet` is not evaluated as a complete geographic model.
It can contain country codes, exclusions, and external geometry references, so
Penge does not claim that it can infer a brand's complete operating region.

## Refresh behavior

The scheduled worker checks for a published version once per day by default.
If the active version is unchanged, it avoids downloading the large catalog.
When a new version is found, Penge downloads the exact tarball from
`registry.npmjs.org`, verifies the SHA-512 integrity value published with the
release metadata, checks the embedded license and version, and validates the
full compiled catalog before staging it.

Only a complete, validated generation is promoted.
A failed or invalid download leaves the previous validated generation intact
and records an explicit stale/failure status for the API.
The refresh status includes the active and candidate release version, checksum,
timestamps, record count, and sanitized error details.
No partial catalog is presented as a complete current index.
To bound local storage, promotion retains the active generation and its
immediate predecessor; older superseded snapshots are removed in the same
transaction as successful promotion.
If a worker exits without recording an outcome, a `refreshing` state older
than two hours is reported as `stale` when a validated generation exists, or
`failed` otherwise; the last validated generation remains searchable.

This is a versioned full-catalog refresh, not a live per-merchant lookup.
No search terms from Penge users are included in public requests.
The public index can suggest possible identities; a local correction remains
authoritative.

## Upstream attribution

The NSI project publishes its catalog under the BSD 3-Clause license and
describes its data sources in its [README](https://github.com/osmlab/name-suggestion-index#about-the-index).
OpenStreetMap's [copyright page](https://www.openstreetmap.org/copyright) states
that OSM data is licensed under the ODbL and describes required attribution.
Penge acknowledges both sources and links the OSM copyright and ODbL notices.
It does not ingest raw OSM data or combine OSM features with private household
data.
