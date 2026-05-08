"""Allocation pie charts by entity, currency, and tax treatment.

Tax treatment grouping is a placeholder until ``account.tax_treatment``
or an equivalent dimension lands; the v1 column does not exist on
``raw.account`` so the third pie is currently driven by
``account.kind`` (e.g. ``aktiesparekonto``, ``frie_midler``,
``pension``) which closely tracks tax treatment for Danish accounts.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from penge.web.data import balance_column


def render(
    panel: pd.DataFrame,
    accounts: pd.DataFrame,
    *,
    currency: str,
) -> None:
    """Render three side-by-side allocation pies: entity, currency, account kind."""
    st.header(f"Allocation — {currency}")

    if panel.empty or accounts.empty:
        st.info("No data yet.")
        return

    column = balance_column(currency)
    latest_date = panel["as_of"].max()
    snapshot = panel.loc[panel["as_of"] == latest_date, ["account_id", column]].dropna()
    if snapshot.empty:
        st.info(f"No {currency}-denominated balances available yet.")
        return

    enriched = snapshot.merge(accounts, on="account_id", how="left")

    col_entity, col_currency, col_kind = st.columns(3)
    col_entity.plotly_chart(
        _pie(enriched, group="entity_name", value=column, title="By entity"),
        use_container_width=True,
    )
    col_currency.plotly_chart(
        _pie(enriched, group="currency", value=column, title="By currency"),
        use_container_width=True,
    )
    col_kind.plotly_chart(
        _pie(enriched, group="account_kind", value=column, title="By account kind"),
        use_container_width=True,
    )


def _pie(df: pd.DataFrame, *, group: str, value: str, title: str) -> object:
    agg = df.groupby(group, as_index=False)[value].sum()
    fig = px.pie(agg, names=group, values=value, title=title, hole=0.4)
    fig.update_layout(margin={"l": 0, "r": 0, "t": 40, "b": 0}, height=320)
    return fig
