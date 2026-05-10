"""Projection dashboard tab (#33).

Renders an interactive Monte-Carlo FIRE projection:

* Goal sliders (target income, SWR, equity weight, initial portfolio,
  capital-gains rate, path count).
* Scenario picker — Baseline, Work reduction, House purchase — each
  with its own parameters.
* Fan chart of p10/p50/p90 portfolio value across the horizon.
* Year-of-FI histogram from
  :attr:`~penge.sim.montecarlo.MonteCarloResult.fire_year_distribution`.
* KPI tiles for ``p_goal_met``, ``median_fire_year``, and ``n_paths``.

The Monte-Carlo run is wrapped in :func:`streamlit.cache_data` keyed
on the hashable widget state so rerendering after a slider change is
sub-second when inputs match a prior run.

The default inputs are demo-grade synthetic values from
:mod:`penge.web.projection_demo`. They render the chart out-of-the-box
and are overridden via the sidebar widgets.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from penge.sim.cashflow import project
from penge.sim.montecarlo import MonteCarloResult, run
from penge.sim.scenario import (
    HousePurchaseScenario,
    WorkReductionScenario,
    compare,
)
from penge.web import projection_demo as demo

_SCENARIOS = ("Baseline", "Work reduction", "House purchase")


@dataclass(frozen=True)
class _Inputs:
    """Hashable bundle of widget state — used as a cache key."""

    target_annual_eur: int
    swr_rate_bp: int
    equity_weight_pct: int
    initial_portfolio_eur: int
    cg_rate_bp: int
    n_paths: int
    horizon_years: int
    scenario: str
    work_red_year: int
    work_red_fte_pct: int
    house_year: int
    house_price_eur: int
    house_down_eur: int
    house_rate_bp: int
    house_term_years: int


def _gather_inputs() -> _Inputs:
    """Render the widgets and collect their values into ``_Inputs``."""
    st.subheader("Goal")
    col_a, col_b, col_c = st.columns(3)
    target_annual_eur = col_a.slider(
        "Target annual income (EUR)",
        min_value=12_000,
        max_value=120_000,
        value=int(demo.DEFAULT_TARGET_ANNUAL_EUR),
        step=1_000,
    )
    swr_rate_bp = col_b.slider(
        "Safe withdrawal rate (bp)",
        min_value=200,
        max_value=600,
        value=int(demo.DEFAULT_SWR_RATE * Decimal("10000")),
        step=25,
        help="100 bp = 1.00 %",
    )
    initial_portfolio_eur = col_c.slider(
        "Initial portfolio (EUR)",
        min_value=0,
        max_value=2_000_000,
        value=int(demo.DEFAULT_INITIAL_PORTFOLIO_EUR),
        step=10_000,
    )

    st.subheader("Portfolio")
    col_d, col_e, col_f = st.columns(3)
    equity_weight_pct = col_d.slider(
        "Equity weight (%)", min_value=0, max_value=100, value=70, step=5
    )
    cg_rate_bp = col_e.slider(
        "Capital-gains effective rate (bp)",
        min_value=0,
        max_value=4_500,
        value=int(demo.DEFAULT_CAPITAL_GAINS_RATE * Decimal("10000")),
        step=25,
    )
    n_paths = col_f.select_slider(
        "Monte-Carlo paths", options=(500, 1_000, 2_000, 5_000, 10_000), value=2_000
    )
    horizon_years = st.slider(
        "Horizon (years)",
        min_value=10,
        max_value=50,
        value=demo.DEFAULT_HORIZON_YEARS,
        step=1,
    )

    st.subheader("Scenario")
    scenario = st.selectbox("Compare against baseline", options=_SCENARIOS, index=0)

    work_red_year = demo.DEFAULT_BASE_YEAR + 5
    work_red_fte_pct = 80
    house_year = demo.DEFAULT_BASE_YEAR + 3
    house_price_eur = 400_000
    house_down_eur = 80_000
    house_rate_bp = 350
    house_term_years = 25
    if scenario == "Work reduction":
        wr_a, wr_b = st.columns(2)
        work_red_year = wr_a.slider(
            "Reduction start year",
            min_value=demo.DEFAULT_BASE_YEAR + 1,
            max_value=demo.DEFAULT_BASE_YEAR + horizon_years,
            value=work_red_year,
        )
        work_red_fte_pct = wr_b.slider(
            "New FTE (%)", min_value=10, max_value=100, value=work_red_fte_pct, step=5
        )
    elif scenario == "House purchase":
        hp_a, hp_b, hp_c = st.columns(3)
        house_year = hp_a.slider(
            "Purchase year",
            min_value=demo.DEFAULT_BASE_YEAR + 1,
            max_value=demo.DEFAULT_BASE_YEAR + horizon_years,
            value=house_year,
        )
        house_price_eur = hp_b.slider(
            "Price (EUR)",
            min_value=100_000,
            max_value=2_000_000,
            value=house_price_eur,
            step=10_000,
        )
        house_down_eur = hp_c.slider(
            "Down-payment (EUR)",
            min_value=10_000,
            max_value=min(house_price_eur, 1_000_000),
            value=min(house_down_eur, house_price_eur),
            step=5_000,
        )
        hp_d, hp_e = st.columns(2)
        house_rate_bp = hp_d.slider(
            "Mortgage rate (bp)", min_value=0, max_value=1_000, value=house_rate_bp, step=10
        )
        house_term_years = hp_e.slider(
            "Term (years)", min_value=5, max_value=40, value=house_term_years, step=1
        )

    return _Inputs(
        target_annual_eur=target_annual_eur,
        swr_rate_bp=swr_rate_bp,
        equity_weight_pct=equity_weight_pct,
        initial_portfolio_eur=initial_portfolio_eur,
        cg_rate_bp=cg_rate_bp,
        n_paths=n_paths,
        horizon_years=horizon_years,
        scenario=scenario,
        work_red_year=work_red_year,
        work_red_fte_pct=work_red_fte_pct,
        house_year=house_year,
        house_price_eur=house_price_eur,
        house_down_eur=house_down_eur,
        house_rate_bp=house_rate_bp,
        house_term_years=house_term_years,
    )


# Streamlit's ``cache_data`` is typed as an untyped decorator under
# ``mypy --strict``; same suppression as in app.py.
@st.cache_data(ttl=600, show_spinner="Running Monte-Carlo…")  # type: ignore[untyped-decorator]
def _run_mc(inputs: _Inputs) -> MonteCarloResult:
    """Run the Monte-Carlo for the given inputs (baseline or scenario)."""
    cashflow_cfg = demo.default_cashflow_config(horizon_years=inputs.horizon_years)
    tax_cfg = demo.default_tax_config()
    goal = demo.default_goal(
        target_annual_eur=Decimal(inputs.target_annual_eur),
        swr_rate=Decimal(inputs.swr_rate_bp) / Decimal("10000"),
    )
    return_model = demo.default_return_model()
    mc_cfg = demo.default_mc_config(
        n_paths=inputs.n_paths,
        initial_portfolio_eur=Decimal(inputs.initial_portfolio_eur),
        capital_gains_effective_rate=Decimal(inputs.cg_rate_bp) / Decimal("10000"),
        equity_weight=Decimal(inputs.equity_weight_pct) / Decimal("100"),
    )

    if inputs.scenario == "Baseline":
        proj = project(cashflow_cfg)
        return run(proj, tax_cfg, goal, return_model, mc_cfg)

    if inputs.scenario == "Work reduction":
        scen = WorkReductionScenario(
            entity="demo",
            year=inputs.work_red_year,
            fte_fraction=Decimal(inputs.work_red_fte_pct) / Decimal("100"),
        )
    else:  # House purchase
        scen = HousePurchaseScenario(  # type: ignore[assignment]
            year=inputs.house_year,
            price_eur=Decimal(inputs.house_price_eur),
            downpayment_eur=Decimal(inputs.house_down_eur),
            mortgage_rate=Decimal(inputs.house_rate_bp) / Decimal("10000"),
            term_years=inputs.house_term_years,
        )

    comparison = compare(cashflow_cfg, tax_cfg, goal, return_model, mc_cfg, {inputs.scenario: scen})
    return comparison.scenarios[0].mc_result


def _fan_chart(result: MonteCarloResult) -> go.Figure:
    years = sorted(result.p50_portfolio.keys())
    p10 = [float(result.p10_portfolio[y]) for y in years]
    p50 = [float(result.p50_portfolio[y]) for y in years]
    p90 = [float(result.p90_portfolio[y]) for y in years]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=years, y=p90, mode="lines", line={"width": 0}, name="p90", showlegend=False)
    )
    fig.add_trace(
        go.Scatter(
            x=years,
            y=p10,
            mode="lines",
            line={"width": 0},
            fill="tonexty",
            fillcolor="rgba(31, 119, 180, 0.2)",
            name="p10-p90 band",
        )
    )
    fig.add_trace(go.Scatter(x=years, y=p50, mode="lines", line={"width": 2}, name="p50 (median)"))
    fig.update_layout(
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
        height=420,
        yaxis_title="Portfolio (EUR)",
        xaxis_title="Year",
    )
    return fig


def _fi_histogram(result: MonteCarloResult) -> go.Figure | None:
    if not result.fire_year_distribution:
        return None
    rows = sorted(result.fire_year_distribution.items())
    df = pd.DataFrame(rows, columns=["year", "paths"])
    fig = go.Figure(go.Bar(x=df["year"], y=df["paths"], name="Paths reaching FI"))
    fig.update_layout(
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
        height=320,
        yaxis_title="Paths",
        xaxis_title="First FI year",
    )
    return fig


def render() -> None:
    """Render the projection dashboard page."""
    st.header("Projection — Monte-Carlo FIRE")
    st.caption(
        "Synthetic demo data — adjust the sliders to explore. "
        "See ADR-0022 for the data sources and ADR-0014 for the simulator."
    )

    inputs = _gather_inputs()
    result = _run_mc(inputs)

    col_p, col_y, col_n = st.columns(3)
    col_p.metric("P(goal met)", f"{float(result.p_goal_met) * 100:.1f} %")
    col_y.metric(
        "Median FI year",
        str(result.median_fire_year) if result.median_fire_year is not None else "—",
    )
    col_n.metric("Paths", f"{result.n_paths:,}")

    st.subheader("Portfolio fan chart")
    st.plotly_chart(_fan_chart(result), use_container_width=True)

    st.subheader("Year of financial independence")
    fi_fig = _fi_histogram(result)
    if fi_fig is None:
        st.info(
            "No path reached the goal within the horizon. Lower the target or extend the horizon."
        )
    else:
        st.plotly_chart(fi_fig, use_container_width=True)
