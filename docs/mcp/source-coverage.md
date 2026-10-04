# MCP source coverage contract

Issue #344 extends the process-local MCP server with typed, bounded evidence paths for every supported Penge source.
It does not create a network endpoint.
The server remains stdio-only, read-only, and fail-closed under [ADR-0023](../decisions/0023-mcp-server-architecture.md).
Individual pre-existing tool contracts remain documented in the [MCP tool reference](tools.md).
Production workers pass the PostgreSQL URL through `PENGE_DB_URL_FILE`, an
owner-only regular file capped at 16 KiB.
The direct `PENGE_DB_URL` form is retained for local CLI and test use, and
configuring both is rejected.

## Authoritative stdio tool allowlist

`get_source_coverage.tool_allowlist` is the authoritative list that the chat backend must enforce:

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

| Source ID                  | Capabilities                                 | Data-bearing MCP evidence                            | Freshness observation                         |
| -------------------------- | -------------------------------------------- | ---------------------------------------------------- | --------------------------------------------- |
| `gls`                      | transactions, balances                       | transaction search/detail; household report          | account and transaction timestamps            |
| `ebank`                    | transactions, balances                       | transaction search/detail; household report          | account and transaction timestamps            |
| `lunar`                    | transactions, balances                       | transaction search/detail; household report          | account and transaction timestamps            |
| `enable_banking`           | transactions, balances                       | transaction search; cashflow                         | aggregate GLS/EBank/Lunar timestamps          |
| `nordnet`                  | transactions, holdings, balances             | transaction search/detail; source-filtered net worth | account, transaction, and holding timestamps  |
| `pfa`                      | transactions, holdings, balances             | transaction search; source-filtered net worth        | account, transaction, and holding timestamps  |
| `growney`                  | transactions, holdings, balances             | transaction search; source-filtered net worth        | account, transaction, and holding timestamps  |
| `ecb_fx`                   | FX rates                                     | household report; net worth                          | latest EUR/DKK rate date                      |
| `manual_facts`             | manual facts, balances, holdings             | source-filtered net worth                            | `manual` provider account/snapshot timestamps |
| `household_classification` | classifications, allocations, rules, aliases | taxonomy/rule/merchant summaries; transaction detail | classification count and latest audit event   |
| `paypal`                   | payment enrichment                           | transaction detail                                   | latest PayPal detail revision                 |
| `nsi_merchant_reference`   | merchant reference                           | local status/search                                  | active generation completion                  |

Adding a value to `SourceIdSchema` requires a catalog entry at compile time.
The contract test also rejects any supported source without a data-bearing evidence path.
`query_net_worth` fails closed when any selected row lacks the requested EUR
or DKK valuation; null aggregates never become false zero balances.
Nordnet, PFA, and Growney are complete only when account, transaction, and
holding evidence are all observed; manual facts require account and holding
evidence.

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
All value-pattern redaction is applied before the final wire-length bound.
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
The transaction, classification, merchant, and PayPal free-text fields are value-pattern redacted before output.
All detail reads run in one read-only repeatable-read PostgreSQL snapshot.
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
Records are not duplicated to the MCP process stderr by default.
The chat service must not put prompts, transcripts, identities, OAuth tokens, or tool result payloads in either identifier.

## Downstream contracts

### PBI #346 chat backend

- Spawn a local stdio MCP process; never connect to or expose a network MCP endpoint.
- Generate per-person and per-session opaque audit IDs and pass them only through the two environment variables above.
- Compare MCP discovery with `tool_allowlist` and deny startup or calls on any mismatch.
- Allow only the exact tools listed above and validate every tool result against its MCP schema.
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
