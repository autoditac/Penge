# MCP source coverage contract

Issue #344 extends the process-local MCP server with typed, bounded evidence paths for every supported Penge source.
It does not create a network endpoint.
The server remains stdio-only, read-only, and fail-closed under [ADR-0023](../decisions/0023-mcp-server-architecture.md).
Individual pre-existing tool contracts remain documented in the [MCP tool reference](tools.md).
Production workers pass the PostgreSQL URL through `PENGE_DB_URL_FILE`, an
owner-only regular file capped at 16 KiB.
The direct `PENGE_DB_URL` form is retained for local CLI and test use, and
configuring both is rejected.

## Exact read-only registration contract reference

The table below is the exact 17-name Penge MCP registration set.
PBI #346 must pin that set independently in the chat backend.
The chat model's allowlist contains the 16 names below other than the
server-metadata tool `_meta`; `_meta` is not exposed as a model-callable tool.
MCP stdio `tools/list` and `get_source_coverage.tool_allowlist` are
server-reported evidence only; neither value is authoritative for the chat
security boundary.
At startup, PBI #346 must compare `tools/list` against its pinned
17-name registration set.
It must also compare every returned `get_source_coverage.tool_allowlist`
against that same independently pinned registration set and fail closed on
any missing, additional, or changed tool.

| Tool                               | Evidence class                                                 |
| ---------------------------------- | -------------------------------------------------------------- |
| `_meta`                            | Server identity and registered tool names                      |
| `query_net_worth`                  | Bounded EUR/DKK holding and manual-fact aggregates             |
| `query_cashflow`                   | Bounded cashflow aggregates                                    |
| `query_household_report`           | Exact EUR/DKK allocations and missing-FX evidence              |
| `search_household_transactions`    | Bounded transaction search                                     |
| `get_household_transaction_detail` | Stable-ID allocation, classification, audit, and PayPal detail |
| `get_household_taxonomy_summary`   | Bounded category tree summary                                  |
| `get_household_rule_summary`       | Bounded classification-rule summary                            |
| `get_household_merchant_summary`   | Bounded household merchant summary                             |
| `get_merchant_reference_status`    | Local NSI refresh status                                       |
| `search_merchant_reference`        | Bounded local NSI label/alias search                           |
| `get_source_coverage`              | Source capabilities, paths, freshness, and completeness        |
| `compute_tax_year`                 | Bounded tax calculation                                        |
| `run_scenario`                     | Bounded simulation                                             |
| `answer_planning_question`         | Typed planning evidence                                        |
| `search_documents`                 | Redacted document references                                   |
| `suggest_import_mapping`           | Read-only deterministic import suggestions                     |

No arbitrary SQL, mutation tool, raw statement export, raw provider payload, or network MCP transport is registered.

Every listed tool publishes its derived Zod output contract through MCP
`outputSchema`.
Object outputs are returned directly in `structuredContent`; top-level array or
scalar outputs use `{ "result": ... }` because MCP structured output schemas
must be objects.
The existing JSON text content remains available for compatible MCP hosts.

## Source matrix

`get_source_coverage` observes source counts and timestamps from PostgreSQL.
The catalog does not claim that a source is fresh or complete without observed evidence.
Coverage metadata alone is not a data-bearing evidence path.

| Source ID                  | Capabilities                                 | Data-bearing MCP evidence                            | Freshness observation                       |
| -------------------------- | -------------------------------------------- | ---------------------------------------------------- | ------------------------------------------- |
| `gls`                      | transactions, balances                       | transaction search/detail; account-grouped net worth | transaction and balance observations        |
| `ebank`                    | transactions, balances                       | transaction search/detail; account-grouped net worth | transaction and balance observations        |
| `lunar`                    | transactions, balances                       | transaction search/detail; account-grouped net worth | transaction and balance observations        |
| `enable_banking`           | transactions, balances                       | transaction search; cashflow; account net worth      | oldest GLS/EBank/Lunar observation          |
| `nordnet`                  | transactions, holdings, balances             | transaction search/detail; source-filtered net worth | transaction and holding observations        |
| `pfa`                      | transactions, holdings, balances             | transaction search; source-filtered net worth        | transaction and holding observations        |
| `growney`                  | transactions, holdings, balances             | transaction search; source-filtered net worth        | transaction and holding observations        |
| `ecb_fx`                   | FX rates                                     | household report; net worth                          | latest EUR/DKK rate date                    |
| `manual_facts`             | manual facts, balances, holdings             | source-filtered net worth                            | latest `manual` holding observation         |
| `household_classification` | classifications, allocations, rules, aliases | taxonomy/rule/merchant summaries; transaction detail | classification count and latest audit event |
| `paypal`                   | payment enrichment                           | transaction detail                                   | latest accessible PayPal detail revision    |
| `nsi_merchant_reference`   | merchant reference                           | local status/search                                  | active generation completion                |

Adding a value to `SourceIdSchema` requires a catalog entry at compile time.
The contract test also rejects any supported source without a data-bearing evidence path.
`query_net_worth` fails closed when any selected row lacks the requested EUR
or DKK valuation; null aggregates never become false zero balances.
GLS, Evangelische Bank, Lunar, Nordnet, PFA, and Growney are complete only
when account, transaction, and holding/balance evidence are all observed.
Their observation time is the older of the latest transaction and holding
observations; freshness is unknown when either is absent.
For Nordnet, a successful staged import also advances its corresponding
observation time when an included row identifies the account, or when a
committed empty holdings snapshot was explicitly confirmed.
Pending and excluded staged rows do not advance freshness.
Transactions in other account currencies cannot be returned by the EUR/DKK
household transaction tools and therefore make their source partial.
Manual facts require account and holding evidence.
Every observed source account must have at least one holding/balance observation.
For each such account, coverage also checks that the latest
account-date has exactly one net-worth mart row, that its account-currency
balance matches the sum of the latest observed position values, and that
both EUR and DKK values exist.
A missing or mismatched row, or a missing valuation, makes that source partial
with unknown freshness.
A latest position with no market value counts as a missing valuation, even
though the net-worth mart values it as 0.
If the mart itself is unavailable or cannot be read, the coverage call fails
closed.
These checks do not certify historical mart rows, FX accuracy, per-account
transaction synchronization, or the freshness of other derived marts.
`enable_banking` is derived from the GLS, EBank, and Lunar coverage rather
than from summed counts: it is complete only when every constituent is
complete, missing only when every constituent is missing, and otherwise
partial. Its `latest_observed_at` is the oldest constituent observation and
is null (freshness `unknown`) when any constituent has no observation, so one
fresh bank never masks another incomplete or unobserved bank.

For PayPal, `evidence_count` counts every observed detail, including details
that cannot be retrieved.
Coverage is partial if any detail lacks a link to a supported EUR/DKK
transaction that has at most ten linked PayPal details and at most 100
allocations.
Freshness uses only structurally accessible details and is unknown if none is
accessible; an unlinked new import cannot hide stale accessible evidence.
These checks do not turn enrichment into a second ledger entry.

## New tool schemas

All objects are strict Zod schemas; unknown keys are rejected.
Every collection has a fixed maximum and every paged offset has a fixed ceiling.

### `get_source_coverage`

Input:

```ts
{
  source_ids?: SourceId[]; // unique catalog IDs, max 12
}
```

`complete` applies only to the requested set, independently of freshness.
An omitted `source_ids` requests all catalog sources; an empty selection
returns `complete: false`.
A complete subset does not certify the full source catalog.

Output:

```ts
{
  generated_at: string; // ISO timestamp
  transport: "stdio";
  read_only: true;
  source_allowlist: SourceId[];
  tool_allowlist: string[];
  sources: Array<{
    id: SourceId;
    label: string;
    kind: "bank" | "brokerage" | "pension" | "fx" | "manual" |
      "taxonomy" | "enrichment" | "merchant_reference";
    capabilities: string[];
    evidence_paths: Array<{ tool: string; evidence: string }>;
    coverage: {
      completeness: "complete" | "partial" | "missing";
      freshness: "fresh" | "stale" | "unknown";
      latest_observed_at: string | null;
      stale_after_days: number;
      account_count: number;
      transaction_count: number;
      holding_count: number;
      evidence_count: number;
    };
  }>;
  complete: boolean;
}
```

### `search_household_transactions`

Input:

```ts
{
  source?: "gls" | "ebank" | "lunar" | "nordnet" | "pfa" | "growney";
  query?: string; // 2..120, redacted from audit
  account_ids?: string[]; // UUID, max 20
  date_range: { from: string; to: string }; // max 367 days
  limit?: number; // 1..50, default 25
  offset?: number; // 0..5000
}
```

Output contains `generated_at`, paging metadata, total count, and at most 50 rows.
Each row contains a stable transaction UUID, source, opaque account UUID, date, value-pattern-redacted bounded description/counterparty, exact decimal-string amount, EUR/DKK currency, current classification summary, and latest audit-event reference.
Transactions in other account currencies are omitted from both pages and totals; their source remains partial in `get_source_coverage`.
All value-pattern redaction is applied before the final wire-length bound.
`transaction_date` is the UTC calendar date of the booking timestamp, serialized as text by PostgreSQL so the MCP host time zone cannot shift it.
`review_state` is the effective state: a stored approval is reported as `needs_review` once the captured source amount, currency, timestamp, counterparty, or kind drifts, or any linked payment detail has moved past its approved revision, matching `classification_out()` in the household API.
It never contains `transaction.raw`, external account IDs, IBANs, or provider payloads.

### `get_household_transaction_detail`

Input:

```ts
{
  transaction_id: string; // UUID
  source?: "gls" | "ebank" | "lunar" | "nordnet" | "pfa" | "growney";
}
```

Output contains exactly one bank/brokerage ledger row, at most 100 exact decimal-string allocations, the current classification, at most 20 audit-event references, and at most 10 linked PayPal details.
The audit references are the 20 most recent events, not a complete audit
history.
More than 100 allocations or ten linked PayPal details fails the entire
detail call rather than returning an incomplete allocation or enrichment list.
The transaction, classification, merchant, and PayPal free-text fields are value-pattern redacted before output.
All detail reads run in one read-only repeatable-read PostgreSQL snapshot.
`value_date` is a PostgreSQL-serialized calendar date, and `classification.review_state` uses the same effective drift-aware state as search.
The top level always declares `ledger_semantics: "single_source_ledger"`.
Every PayPal record declares `ledger_semantics: "enrichment_only"`.
Raw audit snapshots and PayPal `source_fields` are never returned.

### Household summaries

| Tool                             | Input bounds                                                      | Output                                                 |
| -------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------ |
| `get_household_taxonomy_summary` | optional parent UUID; archived flag; limit 1..50; offset 0..5000  | categories with revision and bounded usage counts      |
| `get_household_rule_summary`     | optional state/merchant UUID; limit 1..50; offset 0..5000         | append-only rule metadata; no evidence JSON            |
| `get_household_merchant_summary` | optional query 2..120; archived flag; limit 1..50; offset 0..5000 | merchant identity and alias/rule/classification counts |

### Local merchant reference

`get_merchant_reference_status` accepts only `source_id: "nsi"` and returns refresh state plus active-generation metadata.
`search_merchant_reference` accepts a query of 2..100 characters, optional category prefix, limit 1..20, and offset 0..1000.
It searches only the active local generation and returns at most ten aliases per result.
Neither tool performs network access.
The `unicode-case-folding` package is intentionally used after NFKC
normalization because ECMAScript locale lowercasing is not Unicode case
folding and diverges from the Python index writer for values such as Greek
final sigma.
Whitespace collapse uses exactly Python's `str.split()` whitespace set
(including U+001C..U+001F and U+0085, excluding U+FEFF) rather than
ECMAScript `\s`, so the needle matches what `normalize_alias()` stored.
That folded needle is compared only with `normalized_alias`, which the Python
writer folded the same way. Labels and category prefixes are not stored
folded, so they use an NFKC/whitespace-normalized but unfolded needle with
PostgreSQL `lower()` applied to both sides; the result rows and `total` use
identical predicates.
`search_household_transactions` and `get_household_merchant_summary` likewise
pass the query unchanged and let PostgreSQL `lower()` fold both the needle and
the stored text, so JavaScript and database case mappings cannot diverge.

## Audit attribution contract

The future chat worker may set `PENGE_MCP_ACTOR_ID` and `PENGE_MCP_SESSION_ID` when it spawns the stdio process.
They must be generated pseudonyms with the exact forms `actor_<ULID>` and
`session_<ULID>`; arbitrary names and email addresses are rejected.

Audit records contain only the pseudonymous IDs, tool name, sorted top-level argument key names, status, duration, timestamp, and bounded error code.
At most 32 validated argument keys matching `[A-Za-z0-9_.-]{1,64}` are
persisted.
Invalid and unknown calls use empty argument metadata and a fixed unknown-tool
name.
No argument values are persisted, including dates, source IDs, stable transaction IDs, prompts, queries, or nested values.
The audit directory and file modes are enforced as `0700` and `0600`, respectively; failures are surfaced.
Short, zero-byte, or failed audit writes fail the tool call and disable further
writes on that logger; operators must inspect and repair any partial JSONL
record before restarting the process.
Records are not duplicated to the MCP process stderr by default.
The chat service must not put prompts, transcripts, identities, OAuth tokens, or tool result payloads in either identifier.

## Downstream contracts

### PBI #346 chat backend

- Spawn a local stdio MCP process; never connect to or expose a network MCP endpoint.
- Generate per-person and per-session opaque audit IDs and pass them only through the two environment variables above.
- Independently pin the 17-name registration set and the 16-name model-callable set above; never derive either trusted set from MCP output.
- Compare stdio `tools/list` and every returned `get_source_coverage.tool_allowlist` separately against the pinned registration set, failing startup or the call closed on any mismatch.
- Expose only the 16 independently pinned model-callable tools and validate every tool result against its MCP schema.
- For a full-evidence gate, request all sources and compare the returned source IDs with an independently expected complete source set.
- Require top-level `complete: true` and every returned source's completeness to be `complete`; evaluate freshness separately.
- Prefer MCP `structuredContent` over reparsing model-facing text.
- Consume object-output evidence fields directly; unwrap `structuredContent.result` only for tools whose Zod output is a top-level array or scalar.
- Treat `source_allowlist`, source IDs, stable transaction IDs, freshness, and completeness as opaque typed evidence.
- Propagate cancellation by terminating the bounded MCP call/process and never persist prompts, transcripts, tool arguments, or tool results in audit storage.
- Treat audit `argumentKeys` as operation-shape metadata only; never add argument values or mirror audit records into captured MCP stderr.

### PBI #343 web UI

- Consume evidence events produced by #346; the browser never talks to MCP directly.
- Render source label, source ID, tool name, freshness, completeness, and stable evidence references without rendering raw tool JSON.
- Present stale, missing, partial, missing-FX, and PayPal enrichment-only states explicitly.
- Preserve exact decimal strings for allocation evidence and keep EUR and DKK labels visible.
- Never present linked PayPal enrichment as a second ledger transaction.
