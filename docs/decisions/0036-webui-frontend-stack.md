# WebUI frontend stack: React Router, TanStack Query, ECharts, zod + OpenAPI types

- Status: proposed
- Date: 2026-05-18
- Issue: [#203](https://github.com/autoditac/Penge/issues/203)

Technical Story: Upgrade the `apps/web` shell (ADR-0033) from a static synthetic
page into a real application on top of the FastAPI read API (ADR-0035).

## Context and Problem Statement

The WebUI needs routing, a server-state data layer, real charts, and a typed
contract with the read API. Each is a long-lived dependency choice in the first
user-facing TypeScript app of the repo, so the selections and their rationale
must be recorded (repo rule: no dependency without a reason an existing one
cannot be used).

## Decision Drivers

- Repo rule: validate all runtime inputs with `zod`; never trust `JSON.parse`.
- Boring, dominant, well-typed libraries over clever or niche ones.
- The committed OpenAPI schema (`docs/api/openapi.json`) is the single contract
  artifact; the UI must fail loudly when it drifts.
- Daily-granularity finance time series (years of points) need zoom/brush
  interactions that survive thousands of points.
- EUR and DKK stay first-class side by side (ADR-0004).

## Considered Options

1. Routing: **React Router v7** vs TanStack Router.
2. Server state: **TanStack Query v5** vs hand-rolled fetch + context.
3. Charts: **Apache ECharts (tree-shaken core)** vs Recharts vs visx.
4. API contract: **openapi-typescript generated types + handwritten zod
   schemas with mutual-assignability checks** vs openapi-fetch vs zod-only.

## Decision Outcome

Chosen: React Router v7 (library mode), TanStack Query v5, Apache ECharts via
a thin in-repo `<EChart>` wrapper with the SVG renderer, and a dual contract —
`openapi-typescript` generates compile-time types from the committed schema
while `zod` schemas validate every response at runtime. Type-level
`MutuallyAssignable` assertions tie the two together, and CI regenerates the
client and fails on diff.

Demo mode (`VITE_PENGE_DEMO=true`) serves deterministic synthetic fixtures via
dynamic import; the production path always reads the API.

### Rationale per choice

- **React Router v7**: the dominant, stable router; file-size and API surface
  are small in library mode. TanStack Router's type-safe params are appealing
  but its ecosystem is younger and the app has four static routes.
- **TanStack Query v5**: caching, retries, stale-time, and loading/error state
  machines that a hand-rolled layer would re-implement worse. Already the de
  facto standard pairing with React.
- **ECharts**: handles multi-year daily series with `dataZoom` brushing out of
  the box, renders donut/bar/line from one option grammar, and needs no
  React-specific bridge package (our wrapper is ~80 lines). Recharts degrades
  on large series and lacks built-in brushing; visx is a low-level toolkit
  that would mean building chart UX from scratch. The tree-shaken core with
  the SVG renderer keeps only used modules in a separate cacheable chunk.
- **openapi-typescript + zod**: zod alone cannot catch contract drift at
  compile time; generated types alone validate nothing at runtime. Generated
  `schema.d.ts` is committed and CI-checked (`pnpm generate:api` must produce
  no diff), and the zod schemas must stay mutually assignable with the
  generated types or the build fails. `openapi-fetch` was rejected because it
  would not remove the zod layer the repo mandates anyway.

### Positive Consequences

- Schema drift between API and UI fails CI twice (type-check + drift step).
- Malformed API payloads surface as typed `PengeApiError`s, not NaN charts.
- Loading/error/empty states are uniform across pages.
- Fixtures are out of the production path but still exercised by tests.

### Negative Consequences

- ECharts is a heavy dependency (~330 kB gzipped chunk) even tree-shaken;
  accepted for a local-first dashboard.
- zod schemas duplicate model shape (mitigated by the assignability checks).
- React Router v7 in library mode forgoes its framework-mode data APIs;
  TanStack Query owns data fetching instead, which is the intended split.

## Links

- Builds on [ADR-0033](0033-reporting-first-react-webui.md) (reporting-first WebUI)
  and [ADR-0035](0035-fastapi-read-api.md) (read API + Decimal-string wire contract).
- Respects [ADR-0004](0004-eur-and-dkk-shown-in-parallel.md) (EUR/DKK parallel display).
- [docs/web/modern-webui.md](../web/modern-webui.md) — architecture overview.
