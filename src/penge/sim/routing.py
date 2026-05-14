"""ASK cap overflow routing — contribution split between ASK and frie midler.

When a saver exhausts the Aktiesparekonto (ASK) cumulative deposit cap they must
redirect any remaining monthly savings to a normal brokerage account (*frie
midler*). This module provides a pure-function engine that computes the correct
DKK split for each projected year, given:

* the ASK cumulative lifetime-deposit cap (``ask_cap_dkk``) — the hard SKAT
  limit on how much may ever be deposited in aggregate into the account;
* the deposits already made (``ask_cumulative_deposits_dkk``) — the running
  total as of the projection start date; and
* the saver's monthly contribution (``monthly_contribution_dkk``).

## Routing algorithm

For each projected year the engine computes:

1. **Remaining ASK room** = max(``ask_cap_dkk`` - cumulative deposits at
   start of year, 0).
2. **Annual contribution** = ``monthly_contribution_dkk`` x 12.
3. **ASK portion** = min(annual contribution, remaining room).
4. **Frie midler portion** = annual contribution - ASK portion.

After the ASK portion is credited, the cumulative-deposit counter advances and
the calculation repeats for the next year.  Once the cap is fully absorbed the
counter stays at ``ask_cap_dkk`` and all subsequent contributions are routed
100 % to frie midler.

## Mid-year overflow

The year where the cap is first reached may receive a *partial* ASK
contribution (the residual room) and a corresponding frie midler overflow.
The :func:`simulate_routing_monthly` helper exposes the same logic at
monthly granularity, making it straightforward to identify the exact calendar
month in which the cap is hit and the first overflow occurs.

## Integration with :mod:`penge.sim.liquid`

The yearly splits produced by :func:`simulate_routing` (or
:func:`route_contributions`) are intended to feed the ``annual_contribution_dkk``
field of separate :class:`~penge.sim.liquid.LiquidDepotConfig` instances — one
for the ASK account, one for the frie midler account.  Run
:func:`~penge.sim.liquid.project_liquid` on each config independently for
tax-aware balance projections.

References:
    * ``penge.tax.aktiesparekonto`` — ASK rate constant and deposit-cap table.
    * :func:`~penge.sim.liquid.ask_cap_for_year` — year-specific cap lookup.
    * Issues #134 (ASK), #135 (Lager vs Realisation), #137 (routing).
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

import pydantic

from penge.sim._decimal_utils import to_decimal as _to_decimal

__all__ = [
    "ContributionRouter",
    "ContributionRoutingError",
    "MonthlyContributionSplit",
    "YearlyContributionSplit",
    "route_contributions",
    "simulate_routing",
    "simulate_routing_monthly",
]

_DP2 = Decimal("0.01")
_MONTHS_PER_YEAR: int = 12


def _q(v: Decimal) -> Decimal:
    return v.quantize(_DP2, rounding=ROUND_HALF_EVEN)


class ContributionRoutingError(Exception):
    """Raised when the :class:`ContributionRouter` configuration is invalid."""


# ──────────────────────────────────────────────────────────────────────────────
# Configuration model
# ──────────────────────────────────────────────────────────────────────────────


class ContributionRouter(pydantic.BaseModel):
    """Immutable routing configuration for ASK → frie midler overflow.

    All monetary fields are in **DKK**.

    Args:
        ask_cap_dkk: SKAT's cumulative lifetime ASK deposit cap applicable
            to the projection horizon (DKK).  Use
            :func:`~penge.sim.liquid.ask_cap_for_year` to obtain a
            year-specific estimate, or supply the confirmed SKAT figure
            directly.  Must be > 0.
        ask_cumulative_deposits_dkk: Net deposits already credited to the
            ASK account as of the projection start date (DKK).  This is
            the SKAT-defined running total tracked by
            ``cumulative_ask_deposits_dkk`` in
            :class:`~penge.sim.liquid.YearlyLiquidFlow`.  Must be ≥ 0 and
            ≤ ``ask_cap_dkk``.
        monthly_contribution_dkk: Monthly savings amount (DKK) available
            for investment.  The router allocates as much of this as
            possible to ASK each month (up to the cap), with any remainder
            flowing to frie midler.  Must be ≥ 0.

    Example::

        from decimal import Decimal
        from penge.sim.routing import ContributionRouter, simulate_routing

        router = ContributionRouter(
            ask_cap_dkk=Decimal("140800"),
            ask_cumulative_deposits_dkk=Decimal("62000"),
            monthly_contribution_dkk=Decimal("15000"),
        )
        for split in simulate_routing(router, n_years=3):
            print(split)
    """

    model_config = pydantic.ConfigDict(frozen=True)

    ask_cap_dkk: Decimal
    ask_cumulative_deposits_dkk: Decimal
    monthly_contribution_dkk: Decimal

    @pydantic.field_validator(
        "ask_cap_dkk",
        "ask_cumulative_deposits_dkk",
        "monthly_contribution_dkk",
        mode="before",
    )
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return _to_decimal(v)

    @pydantic.model_validator(mode="after")
    def _validate(self) -> ContributionRouter:
        if self.ask_cap_dkk <= Decimal("0"):
            raise ValueError("ask_cap_dkk must be > 0")
        if self.ask_cumulative_deposits_dkk < Decimal("0"):
            raise ValueError("ask_cumulative_deposits_dkk must be ≥ 0")
        if self.ask_cumulative_deposits_dkk > self.ask_cap_dkk:
            raise ValueError(
                "ask_cumulative_deposits_dkk must be ≤ ask_cap_dkk; "
                f"got {self.ask_cumulative_deposits_dkk} > {self.ask_cap_dkk}"
            )
        if self.monthly_contribution_dkk < Decimal("0"):
            raise ValueError("monthly_contribution_dkk must be ≥ 0")
        return self

    @property
    def ask_cap_remaining_dkk(self) -> Decimal:
        """Remaining ASK deposit room at the projection start date (DKK)."""
        return _q(self.ask_cap_dkk - self.ask_cumulative_deposits_dkk)

    @property
    def annual_contribution_dkk(self) -> Decimal:
        """Total annual contribution (``monthly_contribution_dkk x 12``, DKK)."""
        return _q(self.monthly_contribution_dkk * _MONTHS_PER_YEAR)


# ──────────────────────────────────────────────────────────────────────────────
# Output models
# ──────────────────────────────────────────────────────────────────────────────


class YearlyContributionSplit(pydantic.BaseModel):
    """Computed contribution split for a single projected year.

    Args:
        year_number: 1-based index of the projected year (1 = first year of
            the projection, 2 = second year, …).
        ask_contribution_dkk: Amount routed to the ASK account this year
            (DKK).  Zero once the cumulative deposit cap is fully absorbed.
        frie_midler_contribution_dkk: Amount routed to the frie midler
            account this year (DKK).  Equals the annual contribution minus
            the ASK contribution.
        ask_cap_remaining_dkk: Residual ASK deposit room at the **end** of
            this year (DKK).  Zero once the cap has been exhausted.
        ask_cap_exhausted: ``True`` when the cumulative deposit cap has been
            fully absorbed by the end of this year (i.e. no further deposits
            to ASK are possible in future years).
    """

    model_config = pydantic.ConfigDict(frozen=True)

    year_number: int
    ask_contribution_dkk: Decimal
    frie_midler_contribution_dkk: Decimal
    ask_cap_remaining_dkk: Decimal
    ask_cap_exhausted: bool


class MonthlyContributionSplit(pydantic.BaseModel):
    """Computed contribution split for a single projected month.

    Args:
        month_number: 1-based index of the projected month.
        ask_contribution_dkk: Amount routed to the ASK account this month
            (DKK).  Zero after the cumulative deposit cap is reached.
        frie_midler_contribution_dkk: Amount routed to frie midler this
            month (DKK).
        cumulative_ask_deposits_dkk: Running total of ASK net deposits
            **including** this month's contribution (DKK).  Reaches
            ``ask_cap_dkk`` at the month when the cap is first exhausted
            and remains constant thereafter.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    month_number: int
    ask_contribution_dkk: Decimal
    frie_midler_contribution_dkk: Decimal
    cumulative_ask_deposits_dkk: Decimal


# ──────────────────────────────────────────────────────────────────────────────
# Core routing functions
# ──────────────────────────────────────────────────────────────────────────────


def route_contributions(
    router: ContributionRouter,
    year: int,
) -> tuple[Decimal, Decimal]:
    """Return ``(ask_contribution, frie_midler_contribution)`` for a given year.

    The function is **pure and stateless**: it computes the cumulative deposit
    total at the start of ``year`` by replaying all prior years internally.
    For bulk projections, :func:`simulate_routing` is more efficient (single
    pass) and returns richer per-year metadata.

    Args:
        router: Validated :class:`ContributionRouter`.
        year: 1-based year number (1 = first projected year).  Must be ≥ 1.

    Returns:
        A ``(ask_contribution_dkk, frie_midler_contribution_dkk)`` tuple,
        both values rounded to 2 decimal places (DKK).

    Raises:
        ContributionRoutingError: If ``year < 1``.

    Examples:
        Year 1 with 78 800 DKK remaining ASK room and 180 000 DKK annual
        contribution::

            router = ContributionRouter(
                ask_cap_dkk=Decimal("140800"),
                ask_cumulative_deposits_dkk=Decimal("62000"),
                monthly_contribution_dkk=Decimal("15000"),
            )
            ask, frie = route_contributions(router, 1)
            # ask == 78800, frie == 101200

        Year 2 (cap already exhausted)::

            ask, frie = route_contributions(router, 2)
            # ask == 0, frie == 180000
    """
    if year < 1:
        raise ContributionRoutingError(f"year must be ≥ 1, got {year}")

    annual = router.annual_contribution_dkk
    cumulative = router.ask_cumulative_deposits_dkk

    # Replay years 1 … year-1 to accumulate deposits up to the start of `year`.
    for _ in range(year - 1):
        room = _q(max(router.ask_cap_dkk - cumulative, Decimal("0")))
        ask_k = min(annual, room)
        cumulative = _q(cumulative + ask_k)

    room = _q(max(router.ask_cap_dkk - cumulative, Decimal("0")))
    ask = _q(min(annual, room))
    frie = _q(annual - ask)
    return ask, frie


def simulate_routing(
    router: ContributionRouter,
    n_years: int,
) -> tuple[YearlyContributionSplit, ...]:
    """Simulate contribution routing over *n_years* projected years.

    Performs a single forward pass (O(n)) returning one
    :class:`YearlyContributionSplit` per year in ascending year order.

    Args:
        router: Validated :class:`ContributionRouter`.
        n_years: Number of years to project.  Must be ≥ 1.

    Returns:
        Tuple of :class:`YearlyContributionSplit` objects, one per year,
        in ascending ``year_number`` order.

    Raises:
        ContributionRoutingError: If ``n_years < 1``.

    Example::

        router = ContributionRouter(
            ask_cap_dkk=Decimal("140800"),
            ask_cumulative_deposits_dkk=Decimal("62000"),
            monthly_contribution_dkk=Decimal("15000"),
        )
        splits = simulate_routing(router, n_years=10)
        # splits[0]: year_number=1, ask=78800, frie=101200
        # splits[1]: year_number=2, ask=0,     frie=180000
        # … (years 3-10 identical to year 2)
    """
    if n_years < 1:
        raise ContributionRoutingError(f"n_years must be ≥ 1, got {n_years}")

    annual = router.annual_contribution_dkk
    cumulative = router.ask_cumulative_deposits_dkk
    results: list[YearlyContributionSplit] = []

    for k in range(1, n_years + 1):
        room = _q(max(router.ask_cap_dkk - cumulative, Decimal("0")))
        ask = _q(min(annual, room))
        frie = _q(annual - ask)
        cumulative = _q(cumulative + ask)
        remaining = _q(max(router.ask_cap_dkk - cumulative, Decimal("0")))
        results.append(
            YearlyContributionSplit(
                year_number=k,
                ask_contribution_dkk=ask,
                frie_midler_contribution_dkk=frie,
                ask_cap_remaining_dkk=remaining,
                ask_cap_exhausted=(remaining == Decimal("0")),
            )
        )

    return tuple(results)


def simulate_routing_monthly(
    router: ContributionRouter,
    n_months: int,
) -> tuple[MonthlyContributionSplit, ...]:
    """Simulate contribution routing at **monthly** granularity.

    Useful for identifying the exact calendar month in which the ASK cap is
    first hit and the frie midler overflow begins.

    Args:
        router: Validated :class:`ContributionRouter`.
        n_months: Number of months to project.  Must be ≥ 1.

    Returns:
        Tuple of :class:`MonthlyContributionSplit` objects, one per month,
        in ascending ``month_number`` order.

    Raises:
        ContributionRoutingError: If ``n_months < 1``.

    Example::

        router = ContributionRouter(
            ask_cap_dkk=Decimal("140800"),
            ask_cumulative_deposits_dkk=Decimal("62000"),
            monthly_contribution_dkk=Decimal("15000"),
        )
        months = simulate_routing_monthly(router, n_months=12)
        # months[0..4]: full 15 000 to ASK (months 1-5)
        # months[5]:    3 800 to ASK, 11 200 to frie (cap hit in month 6)
        # months[6..11]: 0 to ASK, 15 000 to frie (months 7-12)
    """
    if n_months < 1:
        raise ContributionRoutingError(f"n_months must be ≥ 1, got {n_months}")

    monthly = router.monthly_contribution_dkk
    cumulative = router.ask_cumulative_deposits_dkk
    results: list[MonthlyContributionSplit] = []

    for m in range(1, n_months + 1):
        room = _q(max(router.ask_cap_dkk - cumulative, Decimal("0")))
        ask = _q(min(monthly, room))
        frie = _q(monthly - ask)
        cumulative = _q(cumulative + ask)
        results.append(
            MonthlyContributionSplit(
                month_number=m,
                ask_contribution_dkk=ask,
                frie_midler_contribution_dkk=frie,
                cumulative_ask_deposits_dkk=cumulative,
            )
        )

    return tuple(results)
