# Modern WebUI

The modern WebUI is a reporting-first React application in `apps/web`.
It is the cockpit for deterministic household reporting, planning workflows,
and explanation-first AI surfaces.

Since the app-shell upgrade (issue #203) it is a real application: routed
surfaces, live data from the FastAPI read API (ADR-0035), ECharts
visualisations, and a dark/light design system. The frontend stack choices
are recorded in ADR-0036.

## Product principles

1. Classical reports are primary.
   Net worth, cashflow, taxes, liquidity, and readiness must come from typed
   data products or simulation outputs.
2. AI explains; it does not invent numbers.
   Assistant answers must reference MCP tool output, assumptions, risks,
   limitations, and source documents.
3. EUR and DKK remain visible as first-class currencies.
   A UI view may focus on one currency, but it must not silently erase the
   other.
4. Demo data is synthetic.
   Never copy real balances, counterparties, statements, or salaries into
   frontend fixtures.

## Surfaces

- **Overview** — net-worth trend (365 days, EUR + DKK), current allocation by
  kind/currency/entity with donut + table, masked account dimension.
- **Performance** — zoomable multi-year net-worth trend and monthly cashflow
  bars. TWR/MWR returns land with the returns engine (#205, #206).
- **Imports** — documents today's CLI flow; the guided wizard arrives with
  the import-sessions API (#207) and wizard UI (#208).
- **Planning** — labelled synthetic preview of the MCP
  `answer_planning_question` surface until live wiring lands (#210).

## Architecture

- **Routing**: React Router v7 (library mode); all surfaces share the
  `AppShell` layout (sidebar navigation, theme toggle, freshness banner).
- **Data layer**: TanStack Query v5 hooks in `src/api/queries.ts` over a
  typed fetch client (`src/api/client.ts`).
- **Contract**: `pnpm --filter @penge/web generate:api` regenerates
  `src/api/schema.d.ts` from the committed `docs/api/openapi.json`
  (`just web-ui-openapi-client`). zod schemas in `src/api/schemas.ts`
  validate every response at runtime and are type-checked against the
  generated types; CI fails when the generated client drifts.
- **Money**: Decimal values arrive as JSON strings (ADR-0035) and are
  converted to floats only at the display/chart edge (`src/money.ts`).
- **Charts**: tree-shaken Apache ECharts core behind the in-repo `<EChart>`
  wrapper with the SVG renderer.
- **States**: uniform loading, error (with retry and `just api-dev` hint),
  and empty states for every data panel.
- **Demo mode**: `VITE_PENGE_DEMO=true` serves deterministic synthetic
  fixtures (`src/demo/fixtures.ts`) through dynamic import; the production
  path always reads the API. A "Demo data" badge marks the mode.

## AI integration direction

The stable boundary is MCP.
The WebUI can call MCP tools through a backend wrapper, and a future GitHub
Copilot SDK agent can use those same typed tools for multi-step workflows.

Good first AI features:

- explain the current dashboard;
- compare two deterministic scenarios;
- summarize risks and missing assumptions;
- draft a planning memo with evidence links;
- suggest the next stress scenarios to run.

Out of scope for the first WebUI:

- free-form financial advice;
- autonomous assumption changes;
- direct LLM reads of raw statements or raw account data;
- hidden calculations that are not reproduced by deterministic code.

## Local development

End-to-end with live mart data (requires the warehouse from `compose.yaml`):

```bash
just api-dev       # FastAPI read API on 127.0.0.1:8000
just web-ui-dev    # Vite dev server on 127.0.0.1:5173
```

Without a database:

```bash
VITE_PENGE_DEMO=true just web-ui-dev
```

For quality gates:

```bash
just web-ui-build
just web-ui-test
just web-ui-lint
just web-ui-openapi-client   # regenerate the typed API client
```
