"""Household spending and target-expense model for FIRE planning.

Models recurring spending rules, one-off expenses, and inflation
indexing across FIRE lifecycle phases (accumulation, bridge, retirement).

All monetary amounts remain in their source currency (EUR or DKK).
No silent cross-currency conversion is performed. Callers that need
a single consolidated figure must apply an FX rate explicitly.

Public API
----------
- :class:`SpendingPhase` — lifecycle phase enum.
- :class:`OneOffExpense` — single-year expense in EUR or DKK.
- :class:`SpendingRule` — recurring (possibly time-bounded) expense rule.
- :class:`HouseholdSpendingPlan` — collection of rules and one-offs.
- :func:`compute_spending` — returns per-currency totals for a given year/phase.

Design note: inflation is per-rule; there is no global inflation override.
See ``docs/sim/spending.md`` for full usage guidance and assumptions.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from typing import Literal

import pydantic

__all__ = [
    "HouseholdSpendingPlan",
    "OneOffExpense",
    "SpendingPhase",
    "SpendingRule",
    "compute_spending",
]

_TWO_DP = Decimal("0.01")


# ---------------------------------------------------------------------------
# Phase enum
# ---------------------------------------------------------------------------


class SpendingPhase(StrEnum):
    """FIRE lifecycle phase used to filter spending rules.

    - ``ACCUMULATION``: Working years; salary income covers expenses.
    - ``BRIDGE``: After leaving employment but before pension vesting;
      portfolio drawdown or part-time income fills the gap.
    - ``RETIREMENT``: Full pension income phase.
    """

    ACCUMULATION = "accumulation"
    BRIDGE = "bridge"
    RETIREMENT = "retirement"


# ---------------------------------------------------------------------------
# One-off expense
# ---------------------------------------------------------------------------


class OneOffExpense(pydantic.BaseModel):
    """A single non-recurring expense in a specific year.

    Args:
        label: Human-readable description (e.g. ``"kitchen renovation"``).
        year: Calendar year the expense occurs.
        amount: Positive monetary amount in *currency*.
        currency: ``"EUR"`` or ``"DKK"``; no implicit conversion is applied.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    label: str
    year: int
    amount: Decimal
    currency: Literal["EUR", "DKK"]

    @pydantic.model_validator(mode="after")
    def _validate(self) -> OneOffExpense:
        if self.amount <= Decimal("0"):
            raise ValueError(f"OneOffExpense '{self.label}': amount must be positive")
        return self


# ---------------------------------------------------------------------------
# Recurring spending rule
# ---------------------------------------------------------------------------


class SpendingRule(pydantic.BaseModel):
    """A recurring annual-spending rule, optionally time-bounded and inflation-indexed.

    The rule is *active* in a given year if all of the following hold:

    - ``active_from is None`` or ``year >= active_from``
    - ``active_until is None`` or ``year <= active_until``

    The rule *applies* to a phase if:

    - ``phase is None`` (matches every phase), or
    - ``rule.phase == current_phase``

    Inflation compounding uses:

    .. code-block:: text

        effective_amount = annual_amount * (1 + inflation_rate) ** (year - base_year)

    where ``base_year`` defaults to ``inflation_base_year`` if set, then to
    ``active_from`` if set, and finally to ``year`` itself (i.e. no compounding
    when neither bound is known — ``periods == 0`` and ``inflation_rate`` has
    no effect).

    Args:
        label: Human-readable description.
        annual_amount: Base-year annual spending in *currency*.
        currency: ``"EUR"`` or ``"DKK"``; no implicit conversion is applied.
        phase: If ``None``, the rule applies across all phases.
        active_from: First calendar year (inclusive) the rule is active.
        active_until: Last calendar year (inclusive) the rule is active.
        inflation_rate: Per-rule annualised inflation rate; default 2 %.
        inflation_base_year: Explicit base year for inflation compounding.
            Overrides the ``active_from`` fallback.  When this is ``None``
            and ``active_from`` is also ``None``, the effective base year
            equals the target year, which means **no compounding**; pass
            an explicit ``inflation_base_year`` to enable full indexing
            on rules without time bounds.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    label: str
    annual_amount: Decimal
    currency: Literal["EUR", "DKK"]
    phase: SpendingPhase | None = None
    active_from: int | None = None
    active_until: int | None = None
    inflation_rate: Decimal = Decimal("0.02")
    inflation_base_year: int | None = None

    @pydantic.model_validator(mode="after")
    def _validate(self) -> SpendingRule:
        if self.annual_amount <= Decimal("0"):
            raise ValueError(f"SpendingRule '{self.label}': annual_amount must be positive")
        if (
            self.active_from is not None
            and self.active_until is not None
            and self.active_from > self.active_until
        ):
            raise ValueError(
                f"SpendingRule '{self.label}': active_from ({self.active_from}) "
                f"must be <= active_until ({self.active_until})"
            )
        return self

    def is_active(self, year: int) -> bool:
        """Return ``True`` if this rule is active in *year*."""
        if self.active_from is not None and year < self.active_from:
            return False
        return not (self.active_until is not None and year > self.active_until)

    def applies_to_phase(self, phase: SpendingPhase) -> bool:
        """Return ``True`` if this rule applies to *phase*."""
        return self.phase is None or self.phase == phase

    def effective_amount(self, year: int) -> Decimal:
        """Return inflation-adjusted annual amount for *year*.

        The base year is resolved in priority order:

        1. ``inflation_base_year`` (explicit override)
        2. ``active_from`` (rule start year)
        3. ``year`` itself (no compounding — amount returned as-is)

        Args:
            year: Target projection year.

        Returns:
            Inflation-compounded amount, rounded to 2 decimal places.
        """
        base = (
            self.inflation_base_year
            if self.inflation_base_year is not None
            else (self.active_from if self.active_from is not None else year)
        )
        periods = year - base
        if periods == 0:
            return self.annual_amount
        amount = self.annual_amount * (Decimal("1") + self.inflation_rate) ** periods
        return amount.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)


# ---------------------------------------------------------------------------
# Plan container
# ---------------------------------------------------------------------------


class HouseholdSpendingPlan(pydantic.BaseModel):
    """A collection of spending rules and one-off expenses for a household.

    Args:
        rules: List of :class:`SpendingRule` instances.
        one_offs: List of :class:`OneOffExpense` instances.
    """

    rules: list[SpendingRule] = pydantic.Field(default_factory=list)
    one_offs: list[OneOffExpense] = pydantic.Field(default_factory=list)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_spending(
    plan: HouseholdSpendingPlan,
    year: int,
    phase: SpendingPhase,
) -> dict[Literal["EUR", "DKK"], Decimal]:
    """Return per-currency annual spending totals for *year* in *phase*.

    Amounts from ``EUR``-denominated rules are summed separately from
    ``DKK``-denominated rules.  No cross-currency conversion is applied.

    The result dict always contains both ``"EUR"`` and ``"DKK"`` keys;
    a currency with no active spending has a value of ``Decimal("0")``.

    Args:
        plan: Household spending plan.
        year: Target calendar year.
        phase: Current FIRE lifecycle phase.

    Returns:
        ``{"EUR": <total>, "DKK": <total>}`` with 2-decimal-place precision.

    Example:
        >>> from decimal import Decimal
        >>> rule = SpendingRule(
        ...     label="living", annual_amount=Decimal("30000"), currency="EUR"
        ... )
        >>> plan = HouseholdSpendingPlan(rules=[rule])
        >>> compute_spending(plan, 2030, SpendingPhase.ACCUMULATION)
        {'EUR': Decimal('30000'), 'DKK': Decimal('0')}
    """
    total_eur = Decimal("0")
    total_dkk = Decimal("0")

    for rule in plan.rules:
        if not rule.is_active(year):
            continue
        if not rule.applies_to_phase(phase):
            continue
        amount = rule.effective_amount(year)
        if rule.currency == "EUR":
            total_eur += amount
        else:
            total_dkk += amount

    for one_off in plan.one_offs:
        if one_off.year != year:
            continue
        if one_off.currency == "EUR":
            total_eur += one_off.amount
        else:
            total_dkk += one_off.amount

    eur = total_eur.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)
    dkk = total_dkk.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)

    return {"EUR": eur, "DKK": dkk}
