# Household categorization foundation

The `/household` API operates on committed bank transactions, not import staging annotations.
Enable it with `PENGE_HOUSEHOLD_ENABLED=true` only behind the existing trusted local/authenticated deployment boundary.
Disabled access returns `503`; invalid input returns `422`, missing records `404`, and stale revisions or uniqueness conflicts `409`.
Writes serialize with source sync and refresh, append audit events and leave durable refresh intent.
No endpoint modifies raw bank facts.
See [ADR-0050](../decisions/0050-audited-household-categorization.md).

## Contract

Money is signed `Decimal`, serialized as JSON strings, never binary floats.
Bank EUR/DKK allocations must use cents and exactly equal the original bank amount.
UUID category identity survives rename, reparent and archive.
Archived nodes remain available for historical display and retained assignments but cannot receive a new assignment.
Financial category kind is immutable after creation.
Fetch all paginated category pages before building a complete nested tree.
Every list uses `limit` (maximum 500) and `offset`.

| Method and path                                                 | Request / response                                                                             |
| --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `GET /household/categories`                                     | Flat `CategoryOut[]` with parent IDs, kind, order, archive and revision                        |
| `POST /household/categories`                                    | `CategoryWrite` with `expected_revision: 0`                                                    |
| `PATCH /household/categories/{id}`                              | Full `CategoryWrite` with current expected revision                                            |
| `GET /household/merchants`                                      | `MerchantOut[]` with identity type, confirmation and public provenance                         |
| `POST /household/merchants` / `PATCH /household/merchants/{id}` | Full `MerchantWrite`, revision checked                                                         |
| `GET /household/aliases`                                        | `AliasOut[]`, optional `merchant_id`                                                           |
| `POST /household/aliases` / `PATCH /household/aliases/{id}`     | `AliasWrite`, exact provider/normalized-label identity                                         |
| `GET /household/rules`                                          | All immutable `RuleOut` versions, optional `merchant_id`                                       |
| `PATCH /household/rules/{id}`                                   | `expected_version`, `disabled`; enabling re-evaluates evidence, never forces a conflict active |
| `GET /household/transactions`                                   | Native bank facts and effective classification, browse/review filters                          |
| `GET /household/transactions/{id}`                              | Source detail and effective allocation/explanation                                             |
| `GET /household/transactions/{id}/suggestion`                   | Confirmed exact identity rule and source-kind hint; no mutation                                |
| `PATCH /household/transactions/{id}/classification`             | `ClassificationWrite`, atomic splits and reconciliation references                             |
| `POST /household/transactions/{id}/undo`                        | `expected_revision`, `audit_id`; restore prior snapshot as a new protected manual revision     |
| `GET /household/audit?subject_id={id}`                          | Append-only correction history                                                                 |
| `POST /household/rules/{id}/preview`                            | Persist eligible changes from a bounded chronological source page                              |
| `GET /household/previews/{id}`                                  | Persisted exact candidate source/alias/edit snapshots                                          |
| `POST /household/previews/{id}/apply`                           | `{"approve": true}`, all-or-nothing revision-checked historical application                    |
| `GET /household/payment-details`                                | Detail-only provider records, optional `unmatched=true`                                        |

Browse filters include account, provider, merchant, category, treatment, review state, source currency, date interval and text search.
The native amount/currency/date are always returned alongside classification revision and `provenance: manual | rule`.
`source_changed` compares the classification's amount/currency/date/counterparty/kind snapshot with current source facts.
`detail_changed` compares approved detail revisions with current provider source revisions.
Review is required before stale allocations can contribute category totals.
The future household mart must retain the authoritative bank amount as unclassified rather than silently using stale splits.
Existing raw cashflow, investment, tax and net-worth behavior is untouched.

## Corrections and learning

`ClassificationWrite` contains `expected_revision` (zero if absent), treatment, optional merchant, `identity_confirmed`, allocations, reconciliation links, detail links and an explanation.
Treatments are `expense`, `income`, `refund`, `transfer`, `excluded` and `unclassified`.
Unclassified bank movements remain review items with no category allocation, while their signed polarity still keeps headline cashflow truthful: positive credits contribute to income and negative debits contribute to gross expenses. This signed-polarity fallback is shared by the API, the household reporting mart (`reporting_treatment`), and the MCP `query_household_report` tool; it never changes the stored unclassified treatment or creates learning evidence.
Expense/refund categories are expense nodes; income categories are income nodes.
Each category occurs once per allocation set; positive and negative splits cannot cancel into a misleading total.
Transfers/exclusions/unclassified have no financial category allocations.
Transfer references identify another own account's opposite-sign movement; refund references identify an original debit.
References do not infer FX rates or overwrite the referenced source facts.
Both transfer legs must be excluded in downstream reporting; linked counterpart treatment must be reviewed where manual decisions conflict.

Only a household-confirmed stable merchant and consistent single-category human evidence establish a reusable default.
In the WebUI transaction review, select that merchant and explicitly confirm the transaction identity before saving the single-category expense or income correction.
Bulk category changes never establish a new identity; they retain only identity evidence that was already confirmed transaction by transaction.
Processor-only PayPal labels, marketplaces, mixed/split spending and conflicting corrections require review.
Accepted source hints are explanations, never hard assignments.
Alias corrections disable the former identity's rule; undo disables affected defaults.
Corrections do not rewrite old rule versions.
Conflicting evidence or a disabled rule also marks earlier rule-assigned movements for review while retaining their allocations; human overrides remain untouched.
Automatic application during bank sync applies only to newly inserted movements.
Previously imported movements require preview and explicit approval, even if still unclassified.
Manual overrides and existing reconciliation are excluded from rule previews.
Changed source facts preserve the manual decision but increment its revision and flag review.

## PayPal provider integration contract

`penge.household.schemas.PaymentDetailWrite` validates:

- `provider: "paypal"`, stable `source_account_id`, stable `external_id`, optional `connection_id`.
- Original signed `amount`, ISO `currency`, UTC `ts`, optional `merchant_name` and `reference`.
- `event_kind: purchase | refund | funding | unknown`; uncertain provider evidence remains unknown.
- `source_fields`: only `entry_reference`, `transaction_id`, `merchant_category_code`, `bank_code`, `bank_sub_code`, `transaction_date`.

`penge.household.service.upsert_payment_detail(Session, PaymentDetailWrite)` returns `models.PaymentDetail`.
The caller owns the transaction and refresh write intent.
Repeating identical facts retains the detail ID/revision and all approved links; `last_seen_at` advances.
Connection-context-only changes do not invalidate economic detail revisions.
Changed detail facts increment the source revision without overwriting approvals.
Never use a per-consent account UID or mutable transaction ID as the stable unique key.
Never persist payer profiles, shipping details, arbitrary response blobs or raw account identifiers here.
No detail-only import may create an account, canonical transaction, cash holding or standalone expense.

Classification `detail_links` carry `detail_id`, approved `detail_revision`, and signed `bank_amount`.
Their total must exactly equal the signed authoritative bank movement in **bank currency**, regardless of original detail currencies.
Presence means explicit household approval and is audited under the bank classification revision.
Multiple details may enrich one bank movement; explicit many-to-many references support delayed/grouped funding.
Unmatched details contribute no expense.
Foreign gross amounts are matching context, not replacement financial facts.
Any report must keep bank-ledger count/sums unchanged by imports or enrichment, except explicitly confirmed transfer/refund policy.

## Development

```bash
just household-test
just household-lint
just migrate-roundtrip
just api-openapi
just web-ui-openapi-client
```

Schemas live in `src/penge/household/schemas.py`; persistence and service invariants in `models.py` and `service.py`.
The committed OpenAPI schema is `docs/api/openapi.json` and the generated WebUI contract is `apps/web/src/api/schema.d.ts`.
The migration is `bae4c90085b4`, following `0007_account_metadata_overrides`.
All fixtures must remain synthetic.
Dashboard, public merchant refresh, classification-aware reporting and provider adapters are deliberately separate PRs.
