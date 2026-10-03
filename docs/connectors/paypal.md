# PayPal Germany (Enable Banking, detail-only)

Penge can request a personal PayPal Germany connection through the existing
[Enable Banking consent flow](../runbook/enable-banking-consent.md).
The public Enable Banking ASPSP directory lists `PayPal` in country `DE`,
supports `personal` and `business` PSU types, advertises redirect authorization,
and lists a maximum consent validity of 180 days.
This directory entry does **not** prove that Penge's application is entitled
to connect, that an individual consent will succeed, or which transaction
fields and history the account will return.

## Scope and safety

PayPal is a **detail-only enrichment source** for checking-account movements.
Penge does not ingest the PayPal wallet balance or write PayPal rows to the
canonical household ledger.
PayPal payment details cannot create a second expense or income.
Only a user-approved link to an authoritative bank transaction can contribute
merchant or allocation detail to reporting.
The bank transaction's signed amount, currency, and date remain authoritative.
Unmatched details and ambiguous links remain review-only.
Matching by amount or date alone is not sufficient.

The connector never asks for or stores a PayPal password and does not scrape
the PayPal website.
Itemized shopping receipts are not promised by the PSD2 transaction interface.
Do not use the PayPal REST API for this personal-account flow: its standard
live transaction access requires a Business account.
Any paid alternative requires separate approval for provider, cost, privacy,
and credentials.

## Consent

Use **Bank connections** in the Penge WebUI and select **PayPal (DE)**.
The Enable Banking PSU type is explicitly `personal`.
The consent requests transactions but not PayPal wallet balances.
Complete the redirect consent in PayPal, then paste the one-time callback code
and state back into Penge.
The Enable Banking session is stored server-side and reused until it expires or
is revoked; no fresh consent is needed for routine refreshes.
The user/account holder must perform the real authorization.
Do not initiate consent or use account credentials as part of automated tests.

The connection uses the existing Enable Banking application, signing key,
callback, feature gate, and stored-session machinery documented in the
[production consent runbook](../runbook/enable-banking-consent.md).
Production access remains unavailable unless the API deployment is explicitly
configured with its Enable Banking application ID and private key.

Sync stores booked transactions in the household payment-detail table using
the provider, the `DE:`-scoped primary account hash, and `entry_reference`.
The adapter does not invoke the generic Enable Banking ledger or balance
loader. Re-consent can rotate the session account UID without changing the
detail identity; only changed source facts increment the detail revision.

## Source fields and semantics

Enable Banking's generic booked-transaction response can expose the following
typed fields.
Actual presence and usefulness on a personal PayPal connection have not been
verified and must be checked after an account holder authorizes it.

| Detail field | Source | Handling |
| --- | --- | --- |
| Stable detail identity | `entry_reference` | Required; used with provider and the primary `identification_hash` for idempotent sync. |
| Source transaction ID | `transaction_id` | Retained only as a source fact; the API says it may change and it is not a deduplication key. |
| Source amount and currency | `transaction_amount` and `credit_debit_indicator` | Stored signed in the original currency for matching context only; never replaces the bank amount or enters household cashflow. |
| Source date | `booking_date`, then `value_date`, then `transaction_date` | Use the first available date; missing all three is an explicit sync error. |
| Merchant category | `merchant_category_code` | Preserved when supplied; not interpreted as a confirmed merchant identity. |
| Bank transaction codes | `bank_transaction_code.code` and `.sub_code` | Preserved as source clues; not sufficient by themselves to classify a PayPal purchase, refund, or funding movement. |
| Merchant/reference | Outgoing debit counterparty name only when an MCC is present; remittance text | Keep only minimal display-safe values; omit processor labels, incoming-party names, email addresses, address-like text, and free-form notes. An address marker truncates text after that marker so an earlier reference is retained. Availability and accuracy are unverified. |

Enable Banking represents the transaction amount as positive and carries
direction separately: `CRDT` is signed positive and `DBIT` signed negative.
Direction does not establish whether a row is a purchase, refund, wallet
funding, transfer, or foreign-exchange leg.
Until PayPal-specific evidence supports deterministic rules, every detail has
`event_kind=unknown`.
Refunds are not associated to purchases by amount/date similarity; an explicit
source reference or human review is required.

The primary `identification_hash` on `AccountResource` is the account-scoped
key for detail upserts, prefixed with `DE:` and scoped by provider.
Enable Banking documents this primary hash for matching accounts across
sessions, including sessions authorized by different PSUs.
The separate `identification_hashes` alternates are not guaranteed unique and
are never used.
If a PayPal account does not return the primary hash, sync fails explicitly
instead of falling back to the per-session account UID or an account number.
See the
[Enable Banking API reference](https://enablebanking.com/docs/api/reference/).

Only these generic Enable Banking source facts are retained in the typed
source-fields whitelist: `entry_reference`, `transaction_id`,
`merchant_category_code`, `bank_code`, `bank_sub_code`, and
`transaction_date`.
Payer profiles, email addresses, shipping details, account numbers, and the
full provider payload are not stored with payment details.

## History, refresh, and limits

The existing connection sync requests up to 365 days of booked history, follows
Enable Banking continuation keys, and falls back to 90- then 30-day windows
when the ASPSP rejects a longer history request with
`WRONG_TRANSACTIONS_PERIOD`.
Older rows are retained idempotently, but the PayPal-specific available history
is not yet verified.
The stored connection status, consent expiry, last-sync timestamp, and
sanitized error are the operational freshness signals.
An authorized connection is selected by the scheduled Enable Banking refresh.

No live personal-account authorization has been performed for this connector.
Until that account-holder step is completed, successful merchant detail,
history completeness, refund/funding semantics, and matching coverage must be
reported as unverified rather than assumed.
