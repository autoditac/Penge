# Ask Penge product truth and surface brief

## Product truth

Ask Penge is a private, evidence-first explanation surface over deterministic
Penge reports and typed MCP tools.
It is not a calculator of record, transaction editor, autonomous financial
adviser, general-purpose agent, or public chat product.
Numbers remain authoritative only when reproduced by the reporting, tax, or
simulation code that emitted the cited evidence.

The first release supports two separately authorized household actors.
Each person links that person's own GitHub account and Copilot entitlement.
Accounts, credentials, quota, sessions, and SDK storage are never shared.

HydraFusion is experimental and has no fallback.
When the exact `hydrafusion` model ID is unavailable to the current linked
identity, the surface is disabled and explains the external entitlement gate.
One household member's successful check never enables the other member:
entitlement is keyed to the Penge actor, linked GitHub identity, and exact
model ID.

## Surface

The route extends the incumbent AppShell and MUI theme; it does not redesign
the cockpit.
The desktop layout uses a transcript plus evidence rail.
Mobile uses the same transcript with an evidence bottom sheet.
Both preserve EUR and DKK context and current freshness indicators.

The surface may render:

- buffered answer deltas;
- sanitized tool activity without raw arguments or raw tool JSON;
- evidence references, freshness, filters, assumptions, and limitations;
- stop, retry, link, unlink, and reauthenticate actions;
- explicit unavailable-model, disabled, rate-limit, timeout, cancellation,
  stale/missing-data, missing-FX, and interrupted-session states.

It must never render chain-of-thought, OAuth material, raw finance rows, raw
statements, arbitrary SQL, filesystem paths, or MCP diagnostics.

## Interaction and accessibility contract

- Stream updates are buffered before announcement to avoid a noisy live region.
- Transcript and evidence are separate semantic regions.
- Stop/retry and evidence controls are keyboard reachable with visible focus.
- Focus returns predictably after dialogs and mobile sheets close.
- Reduced-motion preferences disable nonessential streaming animation.
- Touch targets, contrast, zoom, viewport, and virtual-keyboard behavior meet
  the repository's WCAG 2.2 AA target.

## Versioned backend contract

Issue #343 consumes a versioned event contract from issue #346.
At minimum it needs ordered delta, sanitized tool/evidence, completion,
cancellation, and typed error events plus stable session/event identifiers.
The UI must reject unknown major versions.

The accepted `issue-344-v1` MCP contract registers `_meta` plus 16 chat tools.
Only the 16 chat tools are model-accessible; `_meta` remains protocol-only.
The UI may advertise complete Penge grounding only when the backend reports
this exact contract version and renders the source-coverage evidence returned
by `get_source_coverage`.

## Current availability

The #345 harness is synthetic and makes no model call.
The token-safe 2026-10-04 model-list check did not return `hydrafusion`, so the
production feature remains disabled.
