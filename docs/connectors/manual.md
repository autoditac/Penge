# Manual entries (cash & real estate)

Some assets — current accounts the user does not connect via PSD2,
real estate valuations, gifts in transit — have no upstream feed.
The `penge-manual` CLI lets the user record those balances and
valuations directly into the operational schema.

Each entry writes a [`holding_snapshot`](../decisions/0007-initial-relational-data-model.md)
row keyed by `(account_id, instrument_id, as_of)`, so re-running the
same command for the same date is idempotent (the value is updated,
not duplicated).

## Data model

Manual entries reuse the standard `entity` → `account` → `instrument`
→ `holding_snapshot` chain. Get-or-create is keyed as follows:

| Layer | Match key | Notes |
|---|---|---|
| `entity` | `(name, kind='person')` | created on first use |
| `account` | `(provider='manual', external_id='<entity_id>:<account_name>')` | unique constraint `ux_account__provider_external_id` |
| `instrument` | `(name, kind, currency)` | `kind='cash'` for balances, `kind='real_estate'` for property |
| `holding_snapshot` | `(account_id, instrument_id, as_of)` | quantity is always `1`; `market_value` carries the entered amount |

## CLI

The package installs a `penge-manual` entry point:

```bash
# Cash balance snapshot
uv run --group db --group manual penge-manual add-balance \
    --entity Rouven \
    --account "DKB Tagesgeld" \
    --currency EUR \
    --balance 12345.67

# Real-estate valuation snapshot
uv run --group db --group manual penge-manual mark-property \
    --entity Rouven \
    --account "Nederbyvej 36" \
    --property "Nederbyvej 36 (DK)" \
    --currency DKK \
    --valuation 4500000
```

Or via the `Justfile` recipes:

```bash
just manual-add-balance --entity Rouven --account "DKB Tagesgeld" \
    --currency EUR --balance 12345.67
just manual-mark-property --entity Rouven --account "Nederbyvej 36" \
    --property "Nederbyvej 36 (DK)" --currency DKK --valuation 4500000
```

Both subcommands accept an optional `--as-of YYYY-MM-DD` (defaults to
today) and an optional `--note` (free-form text, currently logged but
not persisted — a follow-up may move it onto a dedicated column).

## Validation

The CLI rejects bad input *before* opening a DB transaction:

- `--currency` must be a 3-letter ISO-4217 code (case-insensitive,
  normalised to upper-case).
- `--balance` / `--valuation` must parse as `Decimal` and be `>= 0`.
- `--entity`, `--account`, `--property` must be non-empty after
  whitespace stripping.
