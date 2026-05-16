"""Household balance-sheet and liquidity-runway projection."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

import pydantic

from penge.sim.plan import HouseholdProjectionResult

__all__ = [
    "HouseholdBalanceSheet",
    "HouseholdBalanceSheetRow",
    "first_liquidity_depletion",
    "project_balance_sheet",
]

_TWO_DP = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)


class HouseholdBalanceSheetRow(pydantic.BaseModel):
    """Yearly household balance sheet row.

    Args:
        year: Calendar year.
        ask_balance_dkk: Spendable ASK balance.
        frie_midler_balance_dkk: Spendable taxable brokerage balance.
        bridge_balance_dkk: Remaining bridge drawdown balance replacing bridged accounts.
        pension_balance_eur: Locked pension balance in EUR.
        pension_balance_dkk: Locked pension balance converted to DKK.
        spendable_liquidity_dkk: ASK + frie midler + active bridge balances.
        locked_pension_dkk: Pension balance not available for bridge spending.
        total_net_worth_dkk: Spendable liquidity plus locked pension.
        annual_spending_dkk: Household spending need converted to DKK.
        liquidity_runway_months: Months of spending covered by spendable liquidity.
        liquidity_depleted: Whether spendable liquidity is exhausted while spending is positive.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    year: int
    ask_balance_dkk: Decimal
    frie_midler_balance_dkk: Decimal
    bridge_balance_dkk: Decimal
    pension_balance_eur: Decimal
    pension_balance_dkk: Decimal
    spendable_liquidity_dkk: Decimal
    locked_pension_dkk: Decimal
    total_net_worth_dkk: Decimal
    annual_spending_dkk: Decimal
    liquidity_runway_months: Decimal | None
    liquidity_depleted: bool


class HouseholdBalanceSheet(pydantic.BaseModel):
    """Full yearly household balance-sheet projection."""

    model_config = pydantic.ConfigDict(frozen=True)

    rows: tuple[HouseholdBalanceSheetRow, ...]

    def first_liquidity_depletion(self) -> HouseholdBalanceSheetRow | None:
        """Return first year where spendable liquidity is depleted."""

        return first_liquidity_depletion(self)


def project_balance_sheet(result: HouseholdProjectionResult) -> HouseholdBalanceSheet:
    """Project yearly net worth and spendable liquidity from a household result."""

    plan = result.plan
    bridge_account_by_entity = {
        template.entity: template.liquid_account_id for template in plan.bridge_templates
    }
    bridge_start_by_account = {
        template.liquid_account_id: template.bridge_start_year for template in plan.bridge_templates
    }
    bridge_balance_by_year = _bridge_balances_by_year(result, bridge_account_by_entity)
    spending_by_year = {spending.year: spending for spending in result.spending_by_year}

    rows: list[HouseholdBalanceSheetRow] = []
    for year in range(plan.base_year + 1, plan.base_year + plan.horizon_years + 1):
        ask_balance = Decimal("0")
        frie_midler_balance = Decimal("0")
        for projection in result.liquid_projections:
            bridge_start_year = bridge_start_by_account.get(projection.config.account_id)
            if bridge_start_year is not None and year > bridge_start_year:
                continue
            flow = next((item for item in projection.flows if item.year == year), None)
            balance = Decimal("0") if flow is None else flow.closing_balance_dkk
            if projection.config.account_type == "ask":
                ask_balance += balance
            else:
                frie_midler_balance += balance

        bridge_balance = bridge_balance_by_year.get(year, Decimal("0"))
        pension_balance_eur = sum(
            (
                flow.cumulative_pension_eur
                for flow in result.cashflow_net.flows
                if flow.year == year
            ),
            Decimal("0"),
        )
        pension_balance_dkk = _eur_to_dkk(pension_balance_eur, plan.eur_per_dkk)
        spendable_liquidity = _q(ask_balance + frie_midler_balance + bridge_balance)
        annual_spending = Decimal("0")
        if year in spending_by_year:
            spending = spending_by_year[year]
            annual_spending = _q(
                spending.total_dkk + _eur_to_dkk(spending.total_eur, plan.eur_per_dkk)
            )
        runway = _runway_months(spendable_liquidity, annual_spending)
        rows.append(
            HouseholdBalanceSheetRow(
                year=year,
                ask_balance_dkk=_q(ask_balance),
                frie_midler_balance_dkk=_q(frie_midler_balance),
                bridge_balance_dkk=_q(bridge_balance),
                pension_balance_eur=_q(pension_balance_eur),
                pension_balance_dkk=pension_balance_dkk,
                spendable_liquidity_dkk=spendable_liquidity,
                locked_pension_dkk=pension_balance_dkk,
                total_net_worth_dkk=_q(spendable_liquidity + pension_balance_dkk),
                annual_spending_dkk=annual_spending,
                liquidity_runway_months=runway,
                liquidity_depleted=annual_spending > Decimal("0")
                and spendable_liquidity <= Decimal("0"),
            )
        )
    return HouseholdBalanceSheet(rows=tuple(rows))


def first_liquidity_depletion(
    balance_sheet: HouseholdBalanceSheet,
) -> HouseholdBalanceSheetRow | None:
    """Return the first row where spendable assets are exhausted."""

    return next((row for row in balance_sheet.rows if row.liquidity_depleted), None)


def _bridge_balances_by_year(
    result: HouseholdProjectionResult,
    bridge_account_by_entity: dict[str, str],
) -> dict[int, Decimal]:
    bridge_start_by_entity = {
        template.entity: template.bridge_start_year for template in result.plan.bridge_templates
    }
    entity_year_balances: dict[tuple[str, int], Decimal] = {}
    for entity_result in result.bridge_results:
        if entity_result.entity not in bridge_account_by_entity:
            continue
        bridge_start_year = bridge_start_by_entity[entity_result.entity]
        for flow in entity_result.result.monthly_flows:
            year = bridge_start_year + ((flow.month - 1) // 12) + 1
            entity_year_balances[(entity_result.entity, year)] = flow.closing_balance_dkk
    balances: dict[int, Decimal] = {}
    for (_, year), balance in entity_year_balances.items():
        balances[year] = _q(balances.get(year, Decimal("0")) + balance)
    return balances


def _eur_to_dkk(amount_eur: Decimal, eur_per_dkk: Decimal) -> Decimal:
    if eur_per_dkk <= Decimal("0"):
        raise ValueError("eur_per_dkk must be positive")
    return _q(amount_eur / eur_per_dkk)


def _runway_months(
    spendable_liquidity_dkk: Decimal,
    annual_spending_dkk: Decimal,
) -> Decimal | None:
    if annual_spending_dkk <= Decimal("0"):
        return None
    return _q(spendable_liquidity_dkk / (annual_spending_dkk / Decimal("12")))
