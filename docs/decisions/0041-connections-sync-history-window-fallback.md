# 0041 — Connections sync history-window fallback

- **Status:** Accepted
- **Date:** 2026-06-15
- **Deciders:** @autoditac
- **Tags:** ingest, web

## Context and Problem Statement

The in-app Enable Banking sync (ADR-0040) pulls a fixed
`DEFAULT_HISTORY_DAYS = 365` window of booked transactions for every
account on a connection. This works for the **first** sync, which runs
immediately after Strong Customer Authentication (SCA): the ASPSP serves
the full requested history and Penge persists it.

On a later, unattended **Sync now**, GLS Gemeinschaftsbank rejects the
365-day window with the Enable Banking error
`WRONG_TRANSACTIONS_PERIOD: Wrong transactions period requested`, and the
whole sync run fails. This is the well-known PSD2 behaviour: outside the
SCA window an AISP may only retrieve a limited transaction history
(commonly 90 days) without re-authenticating. The exact limit is
ASPSP-specific and not reliably advertised, so we cannot statically pick
one window that is correct for every bank.

## Decision Drivers

- Trustworthiness: a routine sync must keep working without surprising the
  user with a hard failure, and must never silently report success when it
  actually fetched nothing.
- Data completeness: we must not lose historical transactions that were
  already imported.
- Simplicity: avoid coupling the sync to per-ASPSP capability metadata that
  Enable Banking does not always populate.

## Considered Options

1. **Static narrow window** — always request 90 days.
2. **Per-ASPSP `maximum_transaction_history`** — read the advertised limit
   from `GET /aspsps` and clamp `date_from` to it.
3. **Window-fallback ladder** — request the full window, and on
   `WRONG_TRANSACTIONS_PERIOD` retry with progressively narrower windows
   (`365 → 90 → 30`) until one is accepted.

## Decision

We chose **Option 3 (window-fallback ladder)**.

`service.sync` builds a list of candidate windows — the requested
`days` plus any strictly narrower entries from
`HISTORY_FALLBACK_DAYS = (90, 30)` — and tries them in order. On a
`WRONG_TRANSACTIONS_PERIOD` error it retries with the next narrower
window; any other Enable Banking error fails immediately as before. If
even the narrowest window is rejected, the error is recorded
(`last_sync_status = "error"`, `last_error.code = "WRONG_TRANSACTIONS_PERIOD"`)
and surfaced to the caller.

This is safe because the first post-consent sync already imported the
deep history, and the transaction upsert is idempotent
(`ux_transaction__account_id_external_id`, last-write-wins), so a
narrower repeat window re-writes recent rows without dropping older ones.

## Consequences

### Positive

- Routine syncs keep a connection current even after the SCA window
  closes, without manual re-consent.
- No dependency on ASPSP capability metadata that Enable Banking may not
  populate.
- The full history is still captured on the first sync, when the ASPSP
  allows it.

### Negative

- A rejected first attempt costs an extra Enable Banking round-trip per
  account before the fallback succeeds.
- If a connection is *first* synced outside an SCA window (e.g. consent
  restored from persisted state, never freshly authorised), the deep
  history may never be fetched. Re-consent is required to backfill it.

### Neutral

- The fallback ladder is a module-level constant
  (`HISTORY_FALLBACK_DAYS`); tuning it does not change the API surface.

## Links

- Issue #242
- ADR-0040 (in-app Enable Banking consent flow)
- Code: `src/penge/api/connections/service.py` (`sync`, `_history_windows`,
  `_sync_accounts`, `WRONG_TRANSACTIONS_PERIOD`)
- Tests: `tests/api/connections/test_routes.py`
  (`test_sync_falls_back_to_narrower_history_window`,
  `test_sync_reports_error_when_no_window_is_accepted`)
