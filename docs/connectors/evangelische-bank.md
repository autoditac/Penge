# Evangelische Bank (Enable Banking PSD2)

Evangelische Bank (BIC `GENODEF1EK1`) exposes account data through
the European PSD2 AISP API. Penge consumes this via
[Enable Banking](https://enablebanking.com/), which acts as a
regulated AISP aggregator. The transport client is generic
(`penge.ingest.enablebanking`) and is shared with the GLS (#14) and
Lunar (#16) connectors; this page covers the Evangelische
Bank-specific glue.

## One-time setup

1. Sign up at <https://enablebanking.com/> and create an
   **Application**. For development you start in sandbox mode, which
   only connects to the Mock ASPSP (so you cannot do an end-to-end
   test against the real Evangelische Bank until you upgrade to
   production credentials).
2. Generate an RSA-2048 keypair, upload the public key to your
   application, and store the private key with mode `0600`. The
   default location used by the CLI is
   `~/.config/penge/enablebanking-sandbox.pem`.
3. Configure the redirect URL on the application — it must match the
   `--redirect-url` you'll pass to `penge-ebank link`. For local
   testing, `http://localhost:8765/callback` is fine.
4. Export environment:

   ```fish
   set -gx ENABLEBANKING_APPLICATION_ID <your-app-uuid>
   set -gx ENABLEBANKING_KEY_PATH ~/.config/penge/enablebanking-sandbox.pem
   ```

The Enable Banking application is shared across all PSD2 connectors;
you do **not** need a separate app per bank.

## Consent flow

PSD2 consent is PSU-driven; you have to redirect a real browser to
the bank to authenticate. The CLI is split into three subcommands so
you can run each step interactively.

```fish
# 1. Get the consent URL
penge-ebank link --redirect-url http://localhost:8765/callback --days 180
# → prints { "consent_url": "...", "authorization_id": "..." }
# Open consent_url in a browser, log in to Evangelische Bank, approve.
# After approval the browser is redirected to:
#   http://localhost:8765/callback?code=<CODE>&state=...

# 2. Exchange the code for a session
penge-ebank authorize --code <CODE>
# → prints { "session_id": "...", "accounts": [...] }
set -gx EBANK_SESSION_ID <session_id>

# 3. Sync transactions + balance into Postgres
penge-ebank sync --entity-name "Your Name" --days 365
```

The session is valid for the consent duration (capped by
Evangelische Bank at ~180 days). When it expires, repeat steps 1–2.

## Field mapping

The loader produces canonical `transaction` rows from Berlin Group
PSD2 transactions. The mapping is identical to GLS — all of it lives
in the shared `penge.ingest.enablebanking.mapping` module:

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

## Idempotency

Every load is safe to re-run. Transactions are upserted on the
`(account_id, external_id)` constraint
`ux_transaction__account_id_external_id`; balance snapshots on
`(account_id, instrument_id, as_of)`
(`ux_holding_snapshot__account_instrument_as_of`). Re-running with
the same upstream data converges to the same DB state.

## Sandbox limitations

Sandbox applications can only connect to **Mock ASPSPs**, not real
banks. To do a true end-to-end test against Evangelische Bank you
must request production access from Enable Banking. The mock ASPSPs
are sufficient for verifying the consent dance, JWT signing,
pagination, and DB upserts.
