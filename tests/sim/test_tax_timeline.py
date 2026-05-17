"""Tests for household tax-event timelines."""

from __future__ import annotations

from decimal import Decimal

from penge.sim.plan import project_household
from penge.sim.tax_timeline import build_tax_timeline
from tests.sim.planning_output_helpers import household_output_plan


def test_tax_timeline_attributes_household_tax_events() -> None:
    result = project_household(household_output_plan())

    timeline = build_tax_timeline(result)

    assert len(timeline.rows) == 12
    assert timeline.totals.pal_skat_dkk > Decimal("0")
    assert timeline.totals.ask_tax_dkk > Decimal("0")
    assert timeline.totals.frie_midler_aktieindkomst_tax_dkk > Decimal("0")
    assert timeline.totals.dividend_tax_dkk > Decimal("0")
    assert timeline.totals.bridge_withdrawal_tax_dkk > Decimal("0")
    assert timeline.totals.estimated_topskat_dkk > Decimal("0")
    assert timeline.totals.folkepension_modregning_dkk > Decimal("0")
    assert timeline.totals.total_tax_drag_dkk > Decimal("0")
    assert timeline.totals.total_tax_drag_dkk == (
        timeline.totals.pal_skat_dkk
        + timeline.totals.ask_tax_dkk
        + timeline.totals.frie_midler_aktieindkomst_tax_dkk
        + timeline.totals.bridge_withdrawal_tax_dkk
        + timeline.totals.bridge_dividend_tax_dkk
        + timeline.totals.bridge_lager_tax_dkk
        + timeline.totals.estimated_topskat_dkk
    )
    assert any(attr.source == "liquid" for row in timeline.rows for attr in row.attributions)
    assert any(attr.source == "bridge" for row in timeline.rows for attr in row.attributions)


def test_tax_timeline_surfaces_topskat_modregning_and_material_changes() -> None:
    result = project_household(household_output_plan(bridge_horizon_months=12))

    timeline = build_tax_timeline(result)

    warning_codes = {warning.code for warning in timeline.warnings}
    assert "topskat_exposure" in warning_codes
    assert "folkepension_modregning" in warning_codes
    assert "material_tax_drag_change" in warning_codes
    assert timeline.rows[0].topskat_exposure_dkk > Decimal("0")
    assert timeline.rows[-1].folkepension_modregning_dkk > Decimal("0")
