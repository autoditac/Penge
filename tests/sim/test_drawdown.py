"""Tests for drawdown-order planning."""

from __future__ import annotations

from decimal import Decimal

from penge.sim.drawdown import (
    DrawdownAccountKind,
    DrawdownAccountState,
    DrawdownStrategyDefinition,
    build_drawdown_accounts,
    compare_drawdown_strategies,
    default_drawdown_strategies,
    evaluate_drawdown_strategy,
)
from penge.sim.plan import project_household
from tests.sim.planning_output_helpers import household_output_plan


def test_build_drawdown_accounts_from_projection_keeps_accessibility() -> None:
    result = project_household(household_output_plan())

    accounts = build_drawdown_accounts(
        result,
        start_year=2028,
        cash_balance_dkk=Decimal("50000"),
    )

    kinds = {account.kind for account in accounts}
    assert {
        DrawdownAccountKind.CASH,
        DrawdownAccountKind.ASK,
        DrawdownAccountKind.FRIE_MIDLER,
    } <= kinds
    pension = next(account for account in accounts if account.kind == DrawdownAccountKind.PENSION)
    assert pension.accessible_from_year == 2035


def test_drawdown_strategy_reports_tax_depletion_and_balances() -> None:
    accounts = (
        DrawdownAccountState(
            account_id="cash",
            kind=DrawdownAccountKind.CASH,
            balance_dkk=Decimal("20000"),
            cost_basis_dkk=Decimal("20000"),
            accessible_from_year=2025,
        ),
        DrawdownAccountState(
            account_id="frie",
            kind=DrawdownAccountKind.FRIE_MIDLER,
            balance_dkk=Decimal("100000"),
            cost_basis_dkk=Decimal("50000"),
            tax_regime="realisation",
            tax_threshold_dkk=Decimal("67500"),
            accessible_from_year=2025,
        ),
        DrawdownAccountState(
            account_id="ask",
            kind=DrawdownAccountKind.ASK,
            balance_dkk=Decimal("100000"),
            cost_basis_dkk=Decimal("100000"),
            tax_regime="lager",
            accessible_from_year=2025,
        ),
        DrawdownAccountState(
            account_id="pension",
            kind=DrawdownAccountKind.PENSION,
            balance_dkk=Decimal("500000"),
            cost_basis_dkk=Decimal("500000"),
            accessible_from_year=2030,
        ),
    )
    frie_first = DrawdownStrategyDefinition(
        name="frie_first",
        label="Frie first",
        order=(DrawdownAccountKind.FRIE_MIDLER, DrawdownAccountKind.ASK),
        description="Use frie midler before ASK.",
    )
    ask_first = DrawdownStrategyDefinition(
        name="ask_first",
        label="ASK first",
        order=(DrawdownAccountKind.ASK, DrawdownAccountKind.FRIE_MIDLER),
        description="Use ASK before frie midler.",
    )

    taxed = evaluate_drawdown_strategy(
        accounts,
        strategy=frie_first,
        start_year=2025,
        annual_spending_dkk=Decimal("60000"),
        horizon_years=2,
    )
    untaxed_first = evaluate_drawdown_strategy(
        accounts,
        strategy=ask_first,
        start_year=2025,
        annual_spending_dkk=Decimal("60000"),
        horizon_years=2,
    )

    assert taxed.total_tax_paid_dkk > Decimal("0")
    assert untaxed_first.total_tax_paid_dkk < taxed.total_tax_paid_dkk
    assert taxed.depletion_year is None
    assert taxed.remaining_balances_dkk[DrawdownAccountKind.FRIE_MIDLER] < Decimal("100000")


def test_compare_drawdown_strategies_uses_default_planning_orders() -> None:
    accounts = (
        DrawdownAccountState(
            account_id="cash",
            kind=DrawdownAccountKind.CASH,
            balance_dkk=Decimal("50000"),
            cost_basis_dkk=Decimal("50000"),
            accessible_from_year=2025,
        ),
    )

    results = compare_drawdown_strategies(
        accounts,
        start_year=2025,
        annual_spending_dkk=Decimal("40000"),
        horizon_years=2,
    )

    assert len(results) == len(default_drawdown_strategies())
    assert all(result.depletion_year == 2026 for result in results)
