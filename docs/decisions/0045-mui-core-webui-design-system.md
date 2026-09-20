# 0045 — MUI Core with a custom Penge theme for the WebUI design system

- **Status:** Accepted
- **Date:** 2025-06-09
- **Deciders:** @autoditac
- **Tags:** web

## Context and Problem Statement

Issue #271 asked for a Nordnet-inspired, responsive redesign of the whole WebUI (`apps/web`): a deep charcoal/slate look, subtly raised panels, a restrained turquoise accent, dense but legible financial tables, compact KPI strips, a proper responsive shell (desktop drawer, mobile app bar + bottom navigation with >=44px targets), and reusable primitives for panels, metrics, statuses, segmented controls, loading/error/empty states, forms and notifications — without regressing the existing 100/100 Lighthouse accessibility/best-practices baseline in demo mode.

The pre-existing UI (`ADR-0033`, `ADR-0036`) is React 19 + TypeScript + React Router + TanStack Query + ECharts + generated OpenAPI types/zod, styled with hand-written CSS custom properties and utility classes (`.panel`, `.kpiCard`, `.pill`, `.segmented`, `.dataTable`, …). That system has no accessible primitives for dialogs, drawers, snackbars, or a real responsive navigation shell, and hand-rolling all of those (plus focus-trapping, keyboard interaction and reduced-motion handling) to Nordnet-grade polish is a large amount of bespoke a11y work to get right and keep right.

## Decision Drivers

- Need accessible, battle-tested primitives (drawer, app bar, bottom navigation, dialogs, snackbars, form controls) rather than reinventing focus management and ARIA wiring for each one.
- Must preserve React 19 + TS + Router + TanStack Query + ECharts + zod/OpenAPI — this ADR is only about the presentation-layer toolkit.
- Must keep the existing Lighthouse 100/100 (accessibility, best practices) baseline.
- Must support a fully custom, non-generic-Material visual identity (flat surfaces, custom palette, tabular numerals, reduced motion) — "looks like Nordnet-inspired Penge", not "looks like MUI's default demo".
- Minimize bundle/complexity growth and migration risk: five pages (~3,400 lines) with live data-fetching logic that must not regress.
- Any new dependency must be pinned exactly and justified (repository rule: no `latest`, no unexplained new deps).

## Considered Options

1. **MUI Core (`@mui/material`) + MUI X Data Grid Community**, as suggested by prior investigation — full component suite including a dedicated data-grid component for all tables.
2. **MUI Core only, custom theme, no MUI X Data Grid** — reuse MUI's shell/layout/form/feedback primitives, keep the existing bespoke `<table>` markup (now wrapped by a small `TableScroll` primitive) for dense financial tables.
3. **Headless UI kit** (Radix UI / Ariakit) + hand-rolled Nordnet visual layer.
4. **Keep the hand-rolled CSS system**, just extend it with more classes/components for drawers, snackbars, etc.

## Decision

We chose **Option 2: MUI Core with a fully custom Penge theme, explicitly without MUI X Data Grid**.

MUI Core (`@mui/material`, `@mui/icons-material`, `@emotion/react`, `@emotion/styled`) gives us accessible `Drawer`, `AppBar`, `BottomNavigation`, `Dialog`, `Snackbar`/`Alert`, `ToggleButtonGroup`, `TextField`/`Select`, and `Chip` primitives for free, all themeable via a single `createTheme()` call. We built `apps/web/src/theme/tokens.ts` (Nordnet-inspired charcoal/slate + turquoise palette, light and dark) and `apps/web/src/theme/muiTheme.ts` (`buildMuiTheme`) to drive both the MUI theme and the existing CSS custom properties from one source of truth, disable Material's default drop shadows/backgrounds for flat surfaces, respect `prefers-reduced-motion`, and set `borderRadius`/typography to match the Nordnet aesthetic rather than default Material look-and-feel.

We deliberately **did not** adopt MUI X Data Grid. The existing tables in Performance and Imports are not generic sortable/filterable grids: they interleave grouped rows, inline drill-down affordances, per-cell semantic coloring, and CSV-import mapping UI that would require a substantial rewrite to fit the Data Grid's row/column model, for a component whose main benefit (virtualization, column resize/reorder, filter UI) is not what issue #271 asked for. Instead, dense tables keep their existing semantic `<table>` markup — the actual authority for financial figures — wrapped in a new `TableScroll` primitive that provides a horizontal-scroll container with a subtle fade/scroll-shadow affordance so no table can cause page-level horizontal overflow on mobile, while progressive disclosure (card/list views below the `sm` breakpoint) is applied per-page where a full table is not legible on small screens. This keeps the migration mechanical and low-risk (swap wrapper markup, not business logic) and avoids growing the bundle or the number of "authoritative" table-rendering code paths for tax-relevant figures.

## Consequences

### Positive

- Accessible navigation shell (desktop permanent drawer, mobile app bar + bottom navigation, dialogs, snackbars) with correct focus/ARIA behavior out of the box.
- A single custom theme (`buildMuiTheme`) is the one place that encodes the Nordnet palette, typography, spacing and motion rules; CSS custom properties and MUI's palette can never drift because both are derived from `theme/tokens.ts`.
- No new "grid" data model to keep in sync with the OpenAPI/zod-validated API responses; existing table-rendering logic, memoized selectors, and grouped-row rendering are untouched.
- Smaller dependency and bundle footprint than pulling in MUI X Data Grid (and its own theming/i18n/licensing surface) for a use case it does not fit well.

### Negative

- Reusable table primitive (`TableScroll`) is a thin wrapper, not a fully virtualized/sortable/filterable grid — sorting/filtering, if ever required generically, would need bespoke work or a future revisit of this ADR.
- Two parallel styling mechanisms exist during migration: legacy CSS custom properties/utility classes (for not-yet-migrated markup) and MUI's `sx`/theme system. This is intentionally temporary; `styles.css` is trimmed as each page migrates.
- Bundle size grows by MUI Core + Emotion (no MUI X). Mitigated by existing manual chunking in `vite.config.ts`.

### Neutral

- Pages keep their existing data-fetching (`TanStack Query`) and validation (`zod`/generated OpenAPI types) unchanged; this ADR only concerns presentation components.

## Alternatives in detail

### Option 1 — MUI Core + MUI X Data Grid Community

Rejected for the reasons above: the grid's row/column/virtualization model does not match the bespoke drill-down and CSV-mapping tables in Performance/Imports, and adopting it wholesale would mean either flattening those tables to fit the grid (losing existing behavior) or running two different table systems side by side for no net accessibility/behavioral gain over a plain semantic `<table>` with a horizontal-scroll wrapper.

### Option 3 — Headless UI kit (Radix/Ariakit) + hand-rolled visuals

Would require hand-building every layout affordance (drawer transitions, bottom-nav semantics, snackbar queuing) on top of headless primitives — more implementation and testing surface than MUI Core for the same accessibility guarantees, with no offsetting benefit since we are already writing a fully custom theme either way.

### Option 4 — Extend the hand-rolled CSS system

Keeps zero new dependencies, but every acceptance criterion in #271 that needs interactive/accessible chrome (responsive drawer, bottom navigation, dialogs, toasts) would need bespoke focus-trapping, ARIA, and keyboard-interaction code written and tested from scratch, which is exactly the kind of risk a mature component library is meant to remove. Rejected as disproportionate effort for a UI-only concern.

## Links

- Issue: [#271](https://github.com/autoditac/Penge/issues/271)
- Related ADRs: [0033](0033-reporting-first-react-webui.md), [0036](0036-webui-frontend-stack.md)
- Code: `apps/web/src/theme/`, `apps/web/src/components/primitives.tsx`, `apps/web/src/shell/AppShell.tsx`
- Docs: [`docs/web/modern-webui.md`](../web/modern-webui.md)
