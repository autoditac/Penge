"""Today's KPI tile: net worth + MoM/YoY deltas.

Savings rate is intentionally omitted from this skeleton — it requires
a cashflow mart that does not yet exist (issue #25 follow-up). A
placeholder caption flags this so the dashboard does not silently miss
the acceptance criterion.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from penge.web.data import delta_pct, latest_total

_MOM_DAYS = 30
_YOY_DAYS = 365


def render(panel: pd.DataFrame, *, currency: str) -> None:
    """Render the KPI page for the given display currency."""
    st.header(f"Net worth — {currency}")

    if panel.empty:
        st.info(
            "No data yet. Run the loaders (`penge-ecb-fx`, `penge-nordnet`) "
            "and rebuild the marts (`dbt build`) to populate this view."
        )
        return

    total = latest_total(panel, currency)
    mom = delta_pct(panel, currency, days_back=_MOM_DAYS)
    yoy = delta_pct(panel, currency, days_back=_YOY_DAYS)

    col_total, col_mom, col_yoy = st.columns(3)
    col_total.metric(
        label=f"Net worth ({currency})",
        value=_format_money(total, currency),
    )
    col_mom.metric(
        label="MoM",
        value=_format_pct(mom),
        delta=_format_pct(mom),
    )
    col_yoy.metric(
        label="YoY",
        value=_format_pct(yoy),
        delta=_format_pct(yoy),
    )

    st.caption(
        "Savings rate is not yet computed — it depends on the cashflow "
        "mart (follow-up to issue #25)."
    )


def _format_money(value: float | None, currency: str) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f} {currency}"


def _format_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}%"
