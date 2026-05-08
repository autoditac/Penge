# Lunar (Enable Banking PSD2)

[Lunar](https://www.lunar.app/) (BIC `LNHBDKKB`) is a Danish
challenger bank that exposes account data through the European PSD2
AISP API. Penge consumes this via
[Enable Banking](https://enablebanking.com/), which acts as a
regulated AISP aggregator. The transport client is generic
(`penge.ingest.enablebanking`) and is shared with the GLS (#14) and
Evangelische Bank (#15) connectors; this page covers the
Lunar-specific glue, in particular the **Aktiesparekonto** auto-tag.

## One-time setup

The Enable Banking application is shared across all PSD2 connectors;
you do **not** need a separate app per bank. If you've already set
up GLS or Evangelische Bank, the application credentials below are
already in your shell — skip to "Consent flow".

1. Sign up at <https://enablebanking.com/> and create an
   **Application**. For development you start in sandbox mode, which
   only connects to the Mock ASPSP.
2. Generate an RSA-2048 keypair, upload the public key to your
   application, and store the private key with mode `0600`. The
   default location used by the CLI is
   `~/.config/penge/enablebanking-sandbox.pem`.
3. Configure the redirect URL on the application — it must match the
   `--redirect-url` you'll pass to `penge-lunar link`. For local
   testing, `http://localhost:8765/callback` is fine.
4. Export environment:

   ```fish
   set -gx ENABLEBANKING_APPLICATION_ID <your-app-uuid>
   set -gx ENABLEBANKING_KEY_PATH ~/.config/penge/enablebanking-sandbox.pem
   ```

## Consent flow

PSD2 consent is PSU-driven; you have to redirect a real browser to
the bank to authenticate. The CLI is split into three subcommands so
you can run each step interactively.

```fish
# 1. Get the consent URL (Lunar is a DK ASPSP)
penge-lunar link --redirect-url http://localhost:8765/callback --days 180
# → prints { "consent_url": "...", "authorization_id": "..." }
# Open consent_url in a browser, log in to Lunar (MitID), approve.
# After approval the browser is redirected to:
#   http://localhost:8765/callback?code=<CODE>&state=...

# 2. Exchange the code for a session
penge-lunar authorize --code <CODE>
# → prints { "session_id": "...", "accounts": [...] }
set -gx LUNAR_SESSION_ID <session_id>

# 3. Sync transactions + balance into Postgres
#    All authorised accounts are synced. Aktiesparekonto subaccounts
#    are auto-tagged.
penge-lunar sync --entity-name "Your Name" --days 365
```

The session is valid for the consent duration (capped by Lunar at
~180 days). When it expires, repeat steps 1–2.

## Aktiesparekonto auto-tagging

The Aktiesparekonto (ASK) is a Danish tax-advantaged stock savings
account with a 17 % flat *lagerbeskatning* (mark-to-market) tax rate
and an annual contribution cap. Lunar exposes ASK as a separate
subaccount whose Berlin Group `product` field contains
`Aktiesparekonto`.

The connector detects ASK subaccounts and writes
`account.dk_tax_treatment = 'aktiesparekonto'` so downstream tax
models can apply the correct regime. Detection rules
(`penge.ingest.lunar.loader.is_aktiesparekonto`):

1. case-insensitive substring match `aktiesparekonto` in `product`,
   **or**
2. case-insensitive substring match `aktiesparekonto` in `name`
   (defensive fallback for renamed accounts).

To override detection (e.g. in tests), pass
`dk_tax_treatment="aktiesparekonto"` (force) or `dk_tax_treatment=""`
(force `NULL`) when calling `load_account` programmatically.

The `dk_tax_treatment` column was added to `account` by Alembic
revision `0002_add_account_dk_tax`; it is constrained to
the values listed there (today: only `aktiesparekonto`).

## Field mapping

The loader produces canonical `transaction` rows from Berlin Group
PSD2 transactions. The mapping is identical to GLS and Evangelische
Bank — all of it lives in the shared
`penge.ingest.enablebanking.mapping` module:

| Penge column   | Source (Enable Banking / Berlin Group)                                                  |
|----------------|------------------------------------------------------------------------------------------|
| `external_id`  | `entry_reference` (immutable per-account); falls back to `transaction_id`                |
| `ts`           | `booking_date` promoted to UTC midnight; falls back to `value_date`, `transaction_date`  |
| `value_date`   | `value_date` (verbatim)                                                                  |
| `kind`         | `credit_debit_indicator`: `CRDT`→`deposit`, `DBIT`→`withdrawal`                          |
| `amount`       | `transaction_amount.amount` with sign from `credit_debit_indicator` (DBIT negated)       |
| `quantity`     | Always `1` (cash transactions)                                                           |
| `price`        | Mirrors `amount`                                                                         |
| `fee`, `tax`   | Always `0` — PSD2 doesn't surface fees as line items                                     |
| `counterparty` | `debtor.name` for credits, `creditor.name` for debits                                    |
| `description`  | `remittance_information` joined with single spaces; falls back to `note`                 |
| `account_id`   | Synthesised from session UID (Enable Banking `accounts[].uid`)                           |

`holding_snapshot` rows are produced from `GET /accounts/{uid}/balances`,
preferring balance types in this order: `CLBD` (closing booked) → `ITBD`
(interim booked) → `CLAV` (closing available) → `XPCD` (expected).

## Currency

Lunar accounts are denominated in **DKK** by default. The CLI uses the
currency Enable Banking reports per account (Berlin Group `currency`
field) and falls back to DKK if Enable Banking does not return one.
There is no `--currency` override flag; if you need to coerce a
specific subaccount to a different currency, call
`penge.ingest.lunar.load_account(..., currency=...)` directly.

## Idempotency

Every load is safe to re-run. Transactions are upserted on the
`(account_id, external_id)` constraint
`ux_transaction__account_id_external_id`; balance snapshots on
`(account_id, instrument_id, as_of)`
(`ux_holding_snapshot__account_instrument_as_of`). The
`dk_tax_treatment` column is updated on every run from the connector's
detection logic, so a Lunar product reclassification upstream is
reflected on the next sync.

## Sandbox limitations

Sandbox applications can only connect to **Mock ASPSPs**, not real
banks. To do a true end-to-end test against Lunar you must request
production access from Enable Banking. The mock ASPSPs are sufficient
for verifying the consent dance, JWT signing, pagination, and DB
upserts.
