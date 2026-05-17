"""Planning-only drawdown-order comparison for household assets."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from types import MappingProxyType

import pydantic

from penge.sim.liquid import compute_aktieindkomst_tax
from penge.sim.plan import HouseholdProjectionResult

__all__ = [
    "DrawdownAccountKind",
    "DrawdownAccountState",
    "DrawdownResult",
    "DrawdownStrategyDefinition",
    "DrawdownYear",
    "build_drawdown_accounts",
    "compare_drawdown_strategies",
    "default_drawdown_strategies",
    "evaluate_drawdown_strategy",
]

_TWO_DP = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)


class DrawdownAccountKind(StrEnum):
    """Planning account buckets supported by the drawdown-order planner."""

    CASH = "cash"
    ASK = "ask"
    FRIE_MIDLER = "frie_midler"
    PENSION = "pension"


class DrawdownAccountState(pydantic.BaseModel):
    """Starting state for one drawdown account bucket."""

    model_config = pydantic.ConfigDict(frozen=True)

    account_id: str
    kind: DrawdownAccountKind
    balance_dkk: Decimal
    cost_basis_dkk: Decimal
    tax_regime: str = "none"
    tax_threshold_dkk: Decimal = Decimal("0")
    accessible_from_year: int

    @pydantic.field_validator("balance_dkk", "cost_basis_dkk", "tax_threshold_dkk", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: object) -> Decimal:
        return Decimal(str(value))

    @pydantic.model_validator(mode="after")
    def _validate(self) -> DrawdownAccountState:
        if self.balance_dkk < Decimal("0"):
            raise ValueError("balance_dkk must be >= 0")
        if self.cost_basis_dkk < Decimal("0"):
            raise ValueError("cost_basis_dkk must be >= 0")
        if self.tax_threshold_dkk < Decimal("0"):
            raise ValueError("tax_threshold_dkk must be >= 0")
        return self


class DrawdownStrategyDefinition(pydantic.BaseModel):
    """Typed drawdown strategy definition."""

    model_config = pydantic.ConfigDict(frozen=True)

    name: str
    label: str
    order: tuple[DrawdownAccountKind, ...]
    description: str

    @pydantic.model_validator(mode="after")
    def _validate(self) -> DrawdownStrategyDefinition:
        if not self.order:
            raise ValueError("order must not be empty")
        return self


class DrawdownYear(pydantic.BaseModel):
    """Yearly drawdown outcome."""

    model_config = pydantic.ConfigDict(frozen=True)

    year: int
    requested_spending_dkk: Decimal
    gross_withdrawal_dkk: Decimal
    net_spending_funded_dkk: Decimal
    tax_paid_dkk: Decimal
    remaining_balances_dkk: Mapping[DrawdownAccountKind, Decimal]
    warnings: tuple[str, ...] = ()

    @pydantic.field_validator("remaining_balances_dkk", mode="before")
    @classmethod
    def _freeze_remaining_balances(
        cls,
        value: object,
    ) -> Mapping[DrawdownAccountKind, Decimal]:
        return _coerce_balance_mapping(value)


class DrawdownResult(pydantic.BaseModel):
    """Result for one drawdown-order strategy."""

    model_config = pydantic.ConfigDict(frozen=True)

    strategy: DrawdownStrategyDefinition
    years: tuple[DrawdownYear, ...]
    total_tax_paid_dkk: Decimal
    depletion_year: int | None
    remaining_balances_dkk: Mapping[DrawdownAccountKind, Decimal]
    warnings: tuple[str, ...]

    @pydantic.field_validator("remaining_balances_dkk", mode="before")
    @classmethod
    def _freeze_remaining_balances(
        cls,
        value: object,
    ) -> Mapping[DrawdownAccountKind, Decimal]:
        return _coerce_balance_mapping(value)


def default_drawdown_strategies() -> tuple[DrawdownStrategyDefinition, ...]:
    """Return built-in planning drawdown strategies."""

    return (
        DrawdownStrategyDefinition(
            name="cash_first",
            label="Cash first",
            order=(
                DrawdownAccountKind.CASH,
                DrawdownAccountKind.FRIE_MIDLER,
                DrawdownAccountKind.ASK,
                DrawdownAccountKind.PENSION,
            ),
            description="Use cash, then taxable brokerage, then ASK, then pensions.",
        ),
        DrawdownStrategyDefinition(
            name="frie_midler_first",
            label="Frie midler first",
            order=(
                DrawdownAccountKind.FRIE_MIDLER,
                DrawdownAccountKind.CASH,
                DrawdownAccountKind.ASK,
                DrawdownAccountKind.PENSION,
            ),
            description="Realise taxable brokerage before spending ASK assets.",
        ),
        DrawdownStrategyDefinition(
            name="ask_preserve",
            label="Preserve ASK",
            order=(
                DrawdownAccountKind.CASH,
                DrawdownAccountKind.FRIE_MIDLER,
                DrawdownAccountKind.PENSION,
                DrawdownAccountKind.ASK,
            ),
            description="Preserve ASK compounding unless all other accessible assets are gone.",
        ),
        DrawdownStrategyDefinition(
            name="pension_start",
            label="Pension start aware",
            order=(
                DrawdownAccountKind.CASH,
                DrawdownAccountKind.ASK,
                DrawdownAccountKind.FRIE_MIDLER,
                DrawdownAccountKind.PENSION,
            ),
            description="Use liquid assets before pensions become accessible.",
        ),
    )


def build_drawdown_accounts(
    result: HouseholdProjectionResult,
    *,
    start_year: int,
    cash_balance_dkk: Decimal = Decimal("0"),
) -> tuple[DrawdownAccountState, ...]:
    """Build drawdown account buckets from a household projection."""

    accounts: list[DrawdownAccountState] = []
    if cash_balance_dkk > Decimal("0"):
        accounts.append(
            DrawdownAccountState(
                account_id="cash",
                kind=DrawdownAccountKind.CASH,
                balance_dkk=_q(cash_balance_dkk),
                cost_basis_dkk=_q(cash_balance_dkk),
                accessible_from_year=start_year,
            )
        )
    for projection in result.liquid_projections:
        flow = next((item for item in projection.flows if item.year == start_year), None)
        if flow is None:
            continue
        kind = (
            DrawdownAccountKind.ASK
            if projection.config.account_type == "ask"
            else DrawdownAccountKind.FRIE_MIDLER
        )
        accounts.append(
            DrawdownAccountState(
                account_id=projection.config.account_id,
                kind=kind,
                balance_dkk=_q(flow.closing_balance_dkk),
                cost_basis_dkk=_q(flow.cost_basis_dkk),
                tax_regime=projection.config.tax_regime,
                tax_threshold_dkk=projection.config.aktieindkomst_threshold_dkk,
                accessible_from_year=start_year,
            )
        )
    pension_access_year = min(
        (
            member.public_pension_start_year
            for member in result.plan.members
            if member.public_pension_start_year is not None
        ),
        default=start_year,
    )
    pension_balance_eur = sum(
        (
            flow.cumulative_pension_eur
            for flow in result.cashflow_net.flows
            if flow.year == start_year
        ),
        Decimal("0"),
    )
    pension_balance_dkk = _q(pension_balance_eur / result.plan.eur_per_dkk)
    if pension_balance_dkk > Decimal("0"):
        accounts.append(
            DrawdownAccountState(
                account_id="locked-pension",
                kind=DrawdownAccountKind.PENSION,
                balance_dkk=pension_balance_dkk,
                cost_basis_dkk=pension_balance_dkk,
                accessible_from_year=pension_access_year,
            )
        )
    return tuple(accounts)


def compare_drawdown_strategies(
    accounts: tuple[DrawdownAccountState, ...],
    *,
    start_year: int,
    annual_spending_dkk: Decimal,
    horizon_years: int,
    strategies: tuple[DrawdownStrategyDefinition, ...] | None = None,
) -> tuple[DrawdownResult, ...]:
    """Evaluate multiple drawdown strategies against the same starting accounts."""

    selected_strategies = strategies if strategies is not None else default_drawdown_strategies()
    return tuple(
        evaluate_drawdown_strategy(
            accounts,
            strategy=strategy,
            start_year=start_year,
            annual_spending_dkk=annual_spending_dkk,
            horizon_years=horizon_years,
        )
        for strategy in selected_strategies
    )


def evaluate_drawdown_strategy(
    accounts: tuple[DrawdownAccountState, ...],
    *,
    strategy: DrawdownStrategyDefinition,
    start_year: int,
    annual_spending_dkk: Decimal,
    horizon_years: int,
) -> DrawdownResult:
    """Evaluate one drawdown-order strategy.

    This is planning support only. It does not execute trades and does not model
    exact pension taxation; pension buckets are guarded by accessibility years.
    """

    if annual_spending_dkk <= Decimal("0"):
        raise ValueError("annual_spending_dkk must be > 0")
    if horizon_years < 1:
        raise ValueError("horizon_years must be >= 1")

    mutable_accounts = {account.account_id: account for account in accounts}
    years: list[DrawdownYear] = []
    warnings: list[str] = []
    depletion_year: int | None = None
    total_tax = Decimal("0")

    for offset in range(horizon_years):
        year = start_year + offset
        remaining_need = annual_spending_dkk
        gross_withdrawal = Decimal("0")
        tax_paid = Decimal("0")
        row_warnings: list[str] = []
        for kind in strategy.order:
            for account_id in _account_ids_for_kind(mutable_accounts, kind):
                account = mutable_accounts[account_id]
                if account.accessible_from_year > year:
                    if account.kind == DrawdownAccountKind.PENSION:
                        row_warnings.append(
                            f"{account.account_id} inaccessible until "
                            f"{account.accessible_from_year}"
                        )
                    continue
                if remaining_need <= Decimal("0") or account.balance_dkk <= Decimal("0"):
                    continue
                withdrawal, tax = _withdraw_for_net_need(account, remaining_need)
                gross_withdrawal += withdrawal
                tax_paid += tax
                remaining_need = _q(remaining_need - (withdrawal - tax))
                mutable_accounts[account_id] = account.model_copy(
                    update={
                        "balance_dkk": _q(account.balance_dkk - withdrawal),
                        "cost_basis_dkk": _remaining_cost_basis_dkk(account, withdrawal),
                    }
                )
        funded = _q(annual_spending_dkk - max(remaining_need, Decimal("0")))
        if remaining_need > Decimal("0") and depletion_year is None:
            depletion_year = year
            row_warnings.append(f"unfunded spending need {remaining_need} DKK")
        total_tax += tax_paid
        years.append(
            DrawdownYear(
                year=year,
                requested_spending_dkk=_q(annual_spending_dkk),
                gross_withdrawal_dkk=_q(gross_withdrawal),
                net_spending_funded_dkk=funded,
                tax_paid_dkk=_q(tax_paid),
                remaining_balances_dkk=_balances_by_kind(tuple(mutable_accounts.values())),
                warnings=tuple(row_warnings),
            )
        )
        warnings.extend(row_warnings)

    return DrawdownResult(
        strategy=strategy,
        years=tuple(years),
        total_tax_paid_dkk=_q(total_tax),
        depletion_year=depletion_year,
        remaining_balances_dkk=_balances_by_kind(tuple(mutable_accounts.values())),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _account_ids_for_kind(
    accounts: dict[str, DrawdownAccountState],
    kind: DrawdownAccountKind,
) -> tuple[str, ...]:
    return tuple(account.account_id for account in accounts.values() if account.kind == kind)


def _withdraw_for_net_need(
    account: DrawdownAccountState,
    net_need_dkk: Decimal,
) -> tuple[Decimal, Decimal]:
    if account.kind != DrawdownAccountKind.FRIE_MIDLER or account.tax_regime != "realisation":
        withdrawal = min(account.balance_dkk, net_need_dkk)
        return _q(withdrawal), Decimal("0")

    gain_fraction = (
        Decimal("0")
        if account.balance_dkk <= Decimal("0")
        else max(account.balance_dkk - account.cost_basis_dkk, Decimal("0")) / account.balance_dkk
    )
    if gain_fraction <= Decimal("0"):
        withdrawal = min(account.balance_dkk, net_need_dkk)
        return _q(withdrawal), Decimal("0")

    full_tax = _tax_for_frie_midler_withdrawal(account, account.balance_dkk, gain_fraction)
    if account.balance_dkk - full_tax <= net_need_dkk:
        return _q(account.balance_dkk), full_tax

    low = Decimal("0")
    high = account.balance_dkk
    for _ in range(80):
        midpoint = (low + high) / Decimal("2")
        tax = _tax_for_frie_midler_withdrawal(account, midpoint, gain_fraction)
        if midpoint - tax >= net_need_dkk:
            high = midpoint
        else:
            low = midpoint

    withdrawal = min(account.balance_dkk, high.quantize(_TWO_DP, rounding=ROUND_CEILING))
    return withdrawal, _tax_for_frie_midler_withdrawal(account, withdrawal, gain_fraction)


def _tax_for_frie_midler_withdrawal(
    account: DrawdownAccountState,
    withdrawal_dkk: Decimal,
    gain_fraction: Decimal,
) -> Decimal:
    taxable_gain = _q(withdrawal_dkk * gain_fraction)
    return compute_aktieindkomst_tax(
        gain_dkk=taxable_gain,
        threshold_dkk=account.tax_threshold_dkk,
    )


def _remaining_cost_basis_dkk(
    account: DrawdownAccountState,
    withdrawal_dkk: Decimal,
) -> Decimal:
    remaining_balance = _q(account.balance_dkk - withdrawal_dkk)
    if remaining_balance <= Decimal("0") or account.balance_dkk <= Decimal("0"):
        return Decimal("0")
    if account.kind == DrawdownAccountKind.FRIE_MIDLER and account.tax_regime == "realisation":
        return _q(account.cost_basis_dkk * remaining_balance / account.balance_dkk)
    return _q(max(account.cost_basis_dkk - withdrawal_dkk, Decimal("0")))


def _balances_by_kind(
    accounts: tuple[DrawdownAccountState, ...],
) -> Mapping[DrawdownAccountKind, Decimal]:
    balances: dict[DrawdownAccountKind, Decimal] = {
        DrawdownAccountKind.CASH: Decimal("0"),
        DrawdownAccountKind.ASK: Decimal("0"),
        DrawdownAccountKind.FRIE_MIDLER: Decimal("0"),
        DrawdownAccountKind.PENSION: Decimal("0"),
    }
    for account in accounts:
        balances[account.kind] = _q(balances[account.kind] + account.balance_dkk)
    return MappingProxyType(balances)


def _coerce_balance_mapping(value: object) -> Mapping[DrawdownAccountKind, Decimal]:
    if not isinstance(value, Mapping):
        raise ValueError("remaining_balances_dkk must be a mapping")
    return MappingProxyType(
        {_coerce_account_kind(kind): Decimal(str(amount)) for kind, amount in value.items()}
    )


def _coerce_account_kind(value: object) -> DrawdownAccountKind:
    if isinstance(value, DrawdownAccountKind):
        return value
    return DrawdownAccountKind(str(value))
