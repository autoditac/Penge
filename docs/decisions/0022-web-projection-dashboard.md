# 0022 — Streamlit projection dashboard tab

- **Status:** Proposed
- **Date:** 2026-05-10
- **Deciders:** @autoditac
- **Tags:** web, sim, ux

## Context and Problem Statement

The Phase-2 simulation engine (ADR-0014, runner + ADR-0015, scenarios)
already produces everything a household needs to reason about its
FIRE trajectory: per-year p10/p50/p90 portfolio values, the goal
hit-rate `p_goal_met`, and the median first-FI year. Issue #25 shipped
the Streamlit dashboard skeleton with KPI / Time-series / Allocation /
Drill-down pages backed by the dbt marts.

Issue #33 asks for a fifth page that exposes the Monte-Carlo result
interactively: goal sliders, a scenario picker, a fan chart for the
percentile band and a histogram of "year I become financially
independent". The page should render on a fresh checkout — even
before any real data has been ingested — so the demo is usable as
a teaching tool and the test surface stays hermetic.

## Decision

Add a new Streamlit view at `src/penge/web/views/projection.py`,
wired into the sidebar radio in `app.py` as a fifth option. The
view is *self-contained*: it does not read the dbt marts, so it
works on a clean database.

Inputs come from sidebar widgets only:

- target annual income (EUR), SWR (bp), initial portfolio (EUR)
- equity weight (%), capital-gains effective rate (bp), path count,
  horizon
- scenario picker over `{Baseline, Work reduction, House purchase}`
  with each scenario's parameters

The Monte-Carlo run is wrapped in `streamlit.cache_data` keyed on a
hashable `_Inputs` dataclass so re-rendering after a slider change is
sub-second when inputs match a prior run.

A small helper module `penge.web.projection_demo` provides synthetic
defaults for the four sim inputs (cashflow config, tax config, return
model, MC config). The synthetic return history is a deterministic
two-asset bootstrap (equity ~7 %/yr drift, bonds ~2 %/yr drift). It
is **not** a model of any real market; it just gives the chart shape
on first run. A later issue will replace this with a fitted history
loader.

To support the FI-year histogram the runner now exposes
`MonteCarloResult.fire_year_distribution: dict[int, int]`. The field
is additive (defaults to an empty dict) — existing code paths and
tests are unaffected.

## Consequences

### Positive

- The dashboard is interactive on a fresh checkout: no database, no
  ingest run, no manual config required.
- The MC runner now reports the FI-year *distribution* (additive
  field), enabling richer downstream visualisations beyond the
  median.
- Scenario comparisons are exposed in the UI, surfacing the
  ADR-0015 work to non-CLI users.

### Negative

- The synthetic return history could mislead first-time users about
  the realism of the projection. The page caption flags it explicitly
  and the next ingestion-side task is to wire a real history loader.
- A live MC run on every slider change would be expensive; we lean
  on `streamlit.cache_data` plus a small default `n_paths` (2 000)
  to keep interaction snappy. Users who want stable percentile tails
  can dial paths up to 10 000 from the slider.

### Neutral

- The view does not currently surface the scenario *delta vs.
  baseline* (issue #34's territory). It only renders one curve at a
  time. A follow-up can layer baseline + scenario in the same fan
  chart.

## Compliance

- Tests at `tests/web/test_projection.py` cover the AppTest smoke
  path and the cached MC wrapper directly.
- `ruff` and `mypy --strict` (with the existing streamlit/plotly
  override) pass on all new files.
