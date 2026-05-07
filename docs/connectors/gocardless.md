# GoCardless Bank Account Data (PSD2)

[GoCardless Bank Account Data][gc-docs] is Penge's gateway to PSD2
account information for European banks. We use it for GLS Bank,
Evangelische Bank, and Lunar (and any other supported institution we
add later).

[gc-docs]: https://developer.gocardless.com/bank-account-data/overview

This page covers the **base client** (token + read-only endpoints) and
the one-time human consent runbook required before any account can be
read. Mapping the API responses onto Penge's `transaction` table is a
separate concern, tracked in #14 / #15 and friends.

## Credentials

1. Sign up at <https://bankaccountdata.gocardless.com/>.
2. Create a "User Secret" pair (`secret_id` + `secret_key`). These are
   the long-lived credentials Penge uses to mint access tokens.
3. Store them outside the repo:

   ```bash
   export GOCARDLESS_SECRET_ID=...        # uuid
   export GOCARDLESS_SECRET_KEY=...       # 64-char hex
   export GOCARDLESS_TOKEN_CACHE=~/.cache/penge/gocardless-tokens.json
   ```

The token cache is `chmod 600`. Refresh tokens are 30-day credentials —
treat them like passwords.

## Token model

| Token | Lifetime | Issued by | Used for |
|---|---|---|---|
| `access` | 24 h | `POST /token/new/` or `/token/refresh/` | `Authorization: Bearer …` |
| `refresh` | 30 days | `POST /token/new/` | minting fresh access tokens |

[`Client._ensure_access_token`](https://github.com/autoditac/Penge/blob/main/src/penge/ingest/gocardless/client.py)
handles the lifecycle: it serves a cached access token when fresh,
refreshes via the long-lived refresh token when stale, and falls back
to a full re-issue when the refresh token has expired or been revoked.
A 60-second skew on access expiry avoids racing the clock.

## Requisition runbook (consent flow)

PSD2 requires explicit user consent per institution, every 90–180 days
depending on the bank. The flow is one-time-per-cycle and **must be
completed in a browser** — there is no way to automate it.

```python
from penge.ingest.gocardless import Client

with Client.from_env() as client:
    # 1. Find the institution.
    insts = client.list_institutions("DK")
    bank = next(i for i in insts if "Lunar" in i.name)

    # 2. Create a requisition. The reference is your idempotency key.
    req = client.create_requisition(
        institution_id=bank.id,
        redirect="https://example.invalid/return",
        reference="penge-lunar-2026-q2",
        user_language="EN",
    )
    print(req.link)  # ← open this in a browser, complete consent
```

After consent, `req.link` returns the user to the redirect URL with the
requisition status flipped to `LN` (linked):

```python
linked = client.get_requisition(req.id)
assert linked.status == "LN"
for account_id in linked.accounts:
    print(account_id)
```

Persist `req.id` somewhere durable — Penge uses it to refresh accounts
without re-prompting the operator until the consent expires.

## Reading data

```python
balances = client.get_account_balances(account_id)
page = client.get_account_transactions(
    account_id,
    date_from="2026-04-01",
    date_to="2026-04-30",
)
details = client.get_account_details(account_id)  # IBAN, currency, …
```

All return Pydantic v2 models with `Decimal` amounts and dates parsed
to `date` / `datetime`. Unknown fields from the upstream payload are
silently dropped (extra="ignore") so we don't break on schema additions.

## Errors

Any non-2xx response raises `ClientError` with the upstream status and
body. A 401 on a non-token endpoint triggers exactly one transparent
re-auth attempt before re-raising.

## Rate limits

GoCardless throttles per-institution at the access-token layer. The
base client does not retry on 429; callers should back off and retry at
the orchestration level (see #15 / #20).

## Testing

There are **zero live network calls** in tests. Unit tests use
`httpx.MockTransport` with synthetic JSON fixtures
([`tests/ingest/test_gocardless.py`](https://github.com/autoditac/Penge/blob/main/tests/ingest/test_gocardless.py)).
Run them locally:

```bash
uv run --group dev --group http pytest tests/ingest/test_gocardless.py
```
