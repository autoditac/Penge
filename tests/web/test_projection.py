"""Smoke tests for the projection dashboard view (#33).

Drives ``app.py`` via ``streamlit.testing.v1.AppTest`` to verify the
new "Projection" page renders end-to-end against the synthetic demo
inputs and that changing a slider re-renders without raising.

The ``test_run_mc_smoke_*`` cases exercise the projection module's
Monte-Carlo wrapper directly. They do *not* require the
``streamlit.testing`` optional dependency — only the AppTest-driven
cases do.  The skip is therefore scoped to those cases via a fixture
so the wrapper smoke tests still run when the AppTest harness is
absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
import pytest
import streamlit as st

from penge.web import data as data_layer
from penge.web.views import projection as projection_view

if TYPE_CHECKING:
    from streamlit.testing.v1 import AppTest as _AppTest

APP_PATH = Path(__file__).resolve().parents[2] / "src" / "penge" / "web" / "app.py"


def _empty_panel(_since: object) -> pd.DataFrame:
    return pd.DataFrame()


def _empty_accounts() -> pd.DataFrame:
    return pd.DataFrame()


def _apptest() -> type[_AppTest]:
    """Return the optional :class:`AppTest` class or skip the test.

    Importing here (rather than at module level) keeps the
    ``test_run_mc_smoke_*`` cases runnable even when the
    ``streamlit.testing`` extra is missing.
    """
    streamlit_testing = pytest.importorskip("streamlit.testing.v1")
    return streamlit_testing.AppTest  # type: ignore[no-any-return]


# ``pytest.fixture`` is typed loosely; under strict mypy this trips
# ``untyped-decorator``. Same pattern is used in tests/web/test_app_smoke.py.
@pytest.fixture(autouse=True)  # type: ignore[untyped-decorator]  # pytest decorator is untyped under strict mypy
def _patch_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace DB fetchers and clear caches between tests.

    The projection view does not need the DB at all but ``main()``
    still calls the fetchers up-front for the other views — patching
    them keeps tests hermetic.
    """
    monkeypatch.setattr(data_layer, "fetch_net_worth_daily", _empty_panel)
    monkeypatch.setattr(data_layer, "fetch_accounts", _empty_accounts)
    st.cache_data.clear()


def test_projection_view_renders() -> None:
    """The Projection page renders without exceptions and emits headers."""
    app_test_cls: Any = _apptest()
    app = app_test_cls.from_file(str(APP_PATH), default_timeout=60)
    app.run()
    assert not app.exception, [str(e) for e in app.exception]

    app.sidebar.radio[0].set_value("Projection").run()
    assert not app.exception, [str(e) for e in app.exception]

    headers = [h.value for h in app.header]
    assert "Projection — Monte-Carlo FIRE" in headers


def test_projection_view_responds_to_slider_change() -> None:
    """Changing the target-income slider re-renders without errors."""
    app_test_cls: Any = _apptest()
    app = app_test_cls.from_file(str(APP_PATH), default_timeout=60)
    app.run()
    app.sidebar.radio[0].set_value("Projection").run()
    assert not app.exception, [str(e) for e in app.exception]

    # First slider on the page is "Target annual income (EUR)".
    target = app.slider[0]
    target.set_value(60_000).run()
    assert not app.exception, [str(e) for e in app.exception]


def test_run_mc_smoke_baseline() -> None:
    """The cached MC wrapper returns a populated result for the defaults."""
    inputs = projection_view._Inputs(
        target_annual_eur=36_000,
        swr_rate_bp=325,
        equity_weight_pct=70,
        initial_portfolio_eur=250_000,
        cg_rate_bp=2_700,
        n_paths=500,
        horizon_years=20,
        scenario="Baseline",
        work_red_year=2029,
        work_red_fte_pct=80,
        house_year=2027,
        house_price_eur=400_000,
        house_down_eur=80_000,
        house_rate_bp=350,
        house_term_years=25,
    )
    # Bypass Streamlit's cache wrapper by calling the underlying function.
    result = projection_view._run_mc.__wrapped__(inputs)
    assert result.n_paths == 500
    assert len(result.p50_portfolio) == 20
    assert 0 <= float(result.p_goal_met) <= 1
    # With the generous demo defaults the goal should be reachable.
    assert result.fire_year_distribution


def test_run_mc_smoke_house_purchase() -> None:
    """Scenario branch runs end-to-end via ``compare``."""
    inputs = projection_view._Inputs(
        target_annual_eur=36_000,
        swr_rate_bp=325,
        equity_weight_pct=70,
        initial_portfolio_eur=250_000,
        cg_rate_bp=2_700,
        n_paths=500,
        horizon_years=20,
        scenario="House purchase",
        work_red_year=2029,
        work_red_fte_pct=80,
        house_year=2027,
        house_price_eur=300_000,
        house_down_eur=60_000,
        house_rate_bp=350,
        house_term_years=20,
    )
    result = projection_view._run_mc.__wrapped__(inputs)
    assert result.n_paths == 500
