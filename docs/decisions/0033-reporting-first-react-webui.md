# 0033 — Reporting-first React WebUI

- **Status:** Proposed
- **Date:** 2026-05-17
- **Deciders:** @autoditac
- **Tags:** web, mcp, security, ux

## Context and Problem Statement

Penge already has a Streamlit dashboard for the first read-only web surface and
an MCP server that exposes typed AI-facing tools.
The next UI needs to support richer household reporting, scenario exploration,
and explanation-first AI workflows without turning the LLM into the source of
financial truth.

The WebUI must make classical reporting boring and auditable first.
AI features should explain deterministic reports, compare scenarios, and guide
review work while preserving the existing MCP-only data boundary from
[ADR-0005](0005-llm-access-via-mcp-only.md).

## Decision Drivers

- Deterministic financial numbers must come from dbt marts, Python simulation,
  and typed report APIs rather than from generated prose.
- The UI should support modern, componentized interaction beyond Streamlit:
  scenario comparison, evidence drill-downs, and assistant panels.
- Any AI surface must keep assumptions, risks, source links, and limitations
  visible next to the answer.
- Dependencies should be small, pinned, and already aligned with the existing
  TypeScript workspace where possible.

## Considered Options

1. **Keep extending Streamlit** — fastest path, already deployed locally.
2. **React + Vite app in `apps/web`** — modern component shell, pnpm workspace,
   deterministic static first slice.
3. **Server-rendered Next.js app** — strong full-stack story, larger runtime and
   routing surface than needed for the first cockpit.

## Decision

We chose **React + Vite in `apps/web`** for the next WebUI layer.

The first implementation is a static, synthetic reporting cockpit that shows the
intended information architecture:

- overview KPIs for net worth, liquidity runway, FIRE readiness, and FI year;
- classical reporting panel for net worth and spendable liquidity;
- risk register panel for reviewable watch items;
- MCP-backed planning-question panel aligned with `answer_planning_question`.

React is added because the UI needs reusable, stateful components for reports,
scenario labs, and assistant panels.
Vite is added because it is already present in the TypeScript toolchain for
Vitest and gives a small, fast frontend build without committing to a server
framework.
The first slice deliberately avoids charting and UI component dependencies; CSS
and small deterministic components are enough until real report APIs land.

The GitHub Copilot SDK remains a future integration option.
The stable internal boundary is MCP: WebUI AI features should call typed tools
directly or through a backend wrapper, and a future Copilot SDK agent should use
those same tools rather than reading raw finance data.

## Consequences

### Positive

- The repo gains a modern WebUI package without replacing the existing
  Streamlit dashboard immediately.
- The first app runs on synthetic data only, so screenshots and tests stay safe.
- Reporting and AI boundaries are visible in the UI from the first slice.
- Frontend build, lint, and tests reuse the existing pnpm workspace conventions.

### Negative

- React adds another UI surface next to Streamlit during the transition.
- Real data requires a future typed API layer; this PR only establishes the
  component and information architecture.
- Vite dev server is not an authenticated deployment surface; production access
  must still be fronted by private networking or authenticated reverse proxy.

### Neutral

- ADR-0022 remains valid for the Streamlit projection tab.
  This ADR defines the modern WebUI direction that can gradually absorb those
  dashboard concepts.

## Alternatives in detail

### Keep extending Streamlit

Streamlit is useful for quick internal dashboards and already has smoke tests.
It becomes awkward for a richer application shell with persistent assistant
panels, evidence drawers, and report-to-scenario navigation.

### Server-rendered Next.js app

Next.js is a good candidate once authenticated deployment, API routes, and
server-side rendering are required.
For the first cockpit, it adds more framework surface than the current static
reporting shell needs.

## Links

- [ADR-0005 LLM access exclusively via MCP](0005-llm-access-via-mcp-only.md)
- [ADR-0022 Streamlit projection dashboard tab](0022-web-projection-dashboard.md)
- [ADR-0023 MCP server architecture](0023-mcp-server-architecture.md)
- `apps/web/`
- Issue #198
