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
schemas, local stdio MCP configuration for the eight currently implemented tools,
ambient-tool denial, actor/token/storage ownership, sanitized child
environments, and typed unavailable-model errors.
It uses synthetic values and makes no external model call.
It does not start the MCP child, request `tools/list`, or invoke a tool.

The planned `issue-344-v1` MCP server registers `_meta` plus 16 chat tools.
It is not implemented on this PR's current base: repository source currently
defines `_meta` plus eight chat tools.
Production remains blocked until #350 lands and an independent stdio
`tools/list` test proves the exact 17-name registration set.
Only the 16 chat tools may then enter the SDK allowlist; `_meta` remains
protocol-only.

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
   credential, and quota.
   SDK storage is derived from the actor ID below a trusted absolute root.
2. `listModels()` for that actor contains exactly `hydrafusion`.
3. The successful check is persisted for exactly that actor, normalized linked
   GitHub login, and `hydrafusion` model ID.
   A record for another actor or linked identity is rejected.
4. SDK and MCP child environments exclude ambient authentication variables.
5. Real stdio `tools/list` evidence matches `issue-344-v1`.
6. `PENGE_CHAT_MODEL=hydrafusion` and
   `PENGE_CHAT_ENABLE_PRODUCTION=1` are set.
   The deployment switch never substitutes for the actor-scoped record.
7. `PENGE_CHAT_FALLBACK_MODEL` is unset.
8. The runtime uses `mode: "empty"`, denies built-in/custom tools and every
   non-MCP permission request, and starts only the local stdio Penge MCP server.
   It approves once only for a read-only request matching the exact `penge`
   server and configured tool allowlist.
9. Network tests prove no MCP, Copilot runtime, database, or raw tool port is
   reachable.
10. Cancellation, timeout, process cleanup, ephemeral transcripts, redacted
   audits, token encryption/rotation, backup, and rollback tests pass.

If any check fails, keep chat disabled and return a typed unavailable or
disabled error.
