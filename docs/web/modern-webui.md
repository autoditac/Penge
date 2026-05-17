# Modern WebUI

The modern WebUI is a reporting-first React shell in `apps/web`.
It is the target cockpit for deterministic household reporting, planning
workflows, and explanation-first AI surfaces.

The current slice uses synthetic data only.
It exists to establish the product shape before real report APIs are connected.

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

## First cockpit

The first WebUI screen is intentionally small:

- KPI cards for net worth, liquidity runway, FIRE readiness, and median FI year.
- A classical reporting panel for net worth and spendable liquidity.
- A risk register panel for review items.
- An AI assistant boundary panel mirroring the MCP
  `answer_planning_question` tool.

This gives future work a concrete layout while keeping the first PR safe and
auditable.

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

```bash
just web-ui-install
just web-ui-dev
```

For quality gates:

```bash
just web-ui-build
just web-ui-test
just web-ui-lint
```
