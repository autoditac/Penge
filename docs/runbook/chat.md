# Chat architecture proof and production gate

Issue #345 supplies a synthetic architecture proof, not a live chat service.
Production remains disabled because the currently authenticated user's
`listModels()` response did not contain the exact `hydrafusion` ID.

## Validate the synthetic proof

```bash
just chat-feasibility
```

The recipe builds, tests, and lints `@penge/chat-feasibility`.
It proves the pinned SDK configuration shape, empty mode, streaming event
schemas, local stdio MCP config, the exact `issue-344-v1` registration and
chat-exposure sets, ambient-tool denial, actor/token ownership, and typed
unavailable-model errors.
It uses synthetic values and makes no external model call.

The MCP server registers `_meta` plus 16 chat tools.
The SDK allowlist and stdio session expose only the 16 chat tools; `_meta` is
never model-accessible.

## Run the token-safe entitlement check

```bash
just chat-entitlement-check
```

The command uses the currently authenticated Copilot identity and calls only
`listModels()`.
It creates an isolated temporary SDK directory, uses error-only logging, prints
only `exactModel`, `entitled`, and `matchCount`, then deletes the directory.
It never prints a token, login, prompt, or financial data.
Exit status `2` means the exact ID is unavailable.

The 2026-10-04 result was:

```json
{ "exactModel": "hydrafusion", "entitled": false, "matchCount": 0 }
```

Do not create an entitlement record from documentation, a different account,
a display name, or a similar model ID.
Never ask for or use another household member's credentials to run this check.

## Production enablement checklist

Issue #346 may enable a linked actor only after all checks pass:

1. The actor uses that person's own GitHub account, Copilot entitlement, OAuth
   credential, quota, and isolated SDK storage.
2. `listModels()` for that actor contains exactly `hydrafusion`.
3. The successful check is persisted for exactly that actor, normalized linked
   GitHub login, and `hydrafusion` model ID.
   A record for another actor or linked identity is rejected.
4. `PENGE_CHAT_MODEL=hydrafusion` and
   `PENGE_CHAT_ENABLE_PRODUCTION=1` are set.
   The deployment switch never substitutes for the actor-scoped record.
5. `PENGE_CHAT_FALLBACK_MODEL` is unset.
6. The accepted #344 tool-contract version is configured.
7. The runtime uses `mode: "empty"`, denies built-in/custom tools and every
   permission request, and starts only the local stdio Penge MCP server.
8. Network tests prove no MCP, Copilot runtime, database, or raw tool port is
   reachable.
9. Cancellation, timeout, process cleanup, ephemeral transcripts, redacted
   audits, token encryption/rotation, backup, and rollback tests pass.

If any check fails, keep chat disabled and return a typed unavailable or
disabled error.
