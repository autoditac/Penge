"""Household planning snapshot — in-memory data model and builder.

This module defines a **pure Python** data model for the household financial
snapshot that seeds a ``HouseholdPlan``.  It does **not** connect to the
database at runtime; instead it works with plain Python dicts (or dataclass
instances) that the caller provides — typically loaded from the DB and passed
in as synthetic fixtures during testing.

## Snapshot concept

Before running a FIRE simulation the planner needs a single, validated view of
the household's current financial state: which accounts exist, what their
balances are, which holdings they contain, and — critically — which planning
assumptions are *missing* and must be supplied manually.

``HouseholdSnapshot`` is that view.  It is produced by ``SnapshotBuilder``, a
small accumulator that accepts one account and one holding at a time, validates
each entry, and collects all warnings about missing or unsupported data into
``HouseholdSnapshot.missing_assumptions``.

## Account kinds

| Kind          | DK term                   | Tax treatment                      |
|---------------|---------------------------|------------------------------------|
| ``cash``      | Bankkonto / indlånskonto  | Interest taxed as kapitalindkomst  |
| ``ask``       | Aktiesparekonto           | Flat 17 % lager                    |
| ``frie_midler`` | Frie midler depot       | Lager (ABIS) or realisations       |
| ``pension``   | Pensionsdepot (PFA/Nordnet etc.) | PAL-skat / deferred          |
| ``manual``    | Manual / catch-all        | Undefined; human review required   |

## Design rationale

* No database connections — keeps the module fast, side-effect-free, and easy
  to unit-test with synthetic fixtures.
* ``missing_assumptions`` is a *list of strings*, not exceptions, so the
  builder accumulates *all* problems in one pass instead of stopping at the
  first error.
* ``type: ignore[arg-type]`` annotations are used in three places (``kind``
  and ``currency`` in ``add_account``; ``currency`` in ``add_holding``) where
  the raw strings have been validated at runtime but cannot be narrowed to the
  ``Literal`` type by mypy without the ignore; the surrounding validation
  ensures correctness.

See ``docs/sim/snapshot.md`` (issue #176).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

__all__ = [
    "AccountKind",
    "AccountSnapshot",
    "HoldingSnapshot",
    "HouseholdSnapshot",
    "SnapshotBuilder",
]

logger = logging.getLogger(__name__)

AccountKind = Literal["cash", "ask", "frie_midler", "pension", "manual"]

_VALID_KINDS: frozenset[str] = frozenset({"cash", "ask", "frie_midler", "pension", "manual"})
_VALID_CURRENCIES: frozenset[str] = frozenset({"EUR", "DKK"})


@dataclass
class AccountSnapshot:
    """Balance snapshot for a single account.

    Args:
        account_id: Stable identifier — external_id or DB UUID as a string.
        entity_name: Owner name, e.g. ``"lars"`` or ``"sofie"``.  Used to
            group accounts by person in a multi-owner household.
        account_name: Human-readable label, e.g. ``"GLS lønkonto"``.
        kind: Account kind; one of ``"cash"``, ``"ask"``,
            ``"frie_midler"``, ``"pension"``, or ``"manual"``.
        currency: Account base currency; ``"EUR"`` or ``"DKK"``.
        balance: Current balance in ``currency``.
        provider: Data provider slug, e.g. ``"nordnet"``, ``"gls"``,
            ``"pfa"``, ``"manual"``.
        data_source: Human-readable provenance string, e.g.
            ``"EnableBanking 2025-01-15"`` or ``"CSV import 2025-03"``.
        notes: Optional free-text annotation.
    """

    account_id: str
    entity_name: str
    account_name: str
    kind: AccountKind
    currency: Literal["EUR", "DKK"]
    balance: Decimal
    provider: str
    data_source: str
    notes: str = ""


@dataclass
class HoldingSnapshot:
    """Holdings snapshot for a single instrument in an account.

    Args:
        account_id: Matches :attr:`AccountSnapshot.account_id`.
        isin: ISIN of the instrument.
        instrument_name: Human-readable instrument label.
        quantity: Number of units / shares held.
        market_value: Current market value in the account's ``currency``.
        cost_basis: Total cost basis in ``currency``, or ``None`` if the
            source did not provide it.  When ``None``, bridge depletion
            calculations will be approximate; a warning is added to
            ``HouseholdSnapshot.missing_assumptions``.
        currency: Currency of ``market_value`` and ``cost_basis``;
            ``"EUR"`` or ``"DKK"``.
        data_source: Provenance string, same format as
            :attr:`AccountSnapshot.data_source`.
    """

    account_id: str
    isin: str
    instrument_name: str
    quantity: Decimal
    market_value: Decimal
    cost_basis: Decimal | None
    currency: Literal["EUR", "DKK"]
    data_source: str


@dataclass
class HouseholdSnapshot:
    """Complete household financial snapshot for planning purposes.

    Produced by :class:`SnapshotBuilder`.  Contains a validated list of
    account and holding snapshots, plus all warnings about missing or
    unsupported data encountered during construction.

    Args:
        snapshot_date: ISO date string (``YYYY-MM-DD``) for the valuation date.
        accounts: List of :class:`AccountSnapshot` instances.
        holdings: List of :class:`HoldingSnapshot` instances.
        missing_assumptions: Human-readable warnings about data that could not
            be mapped or is absent.  An empty list means the snapshot is
            complete and ready to seed a ``HouseholdPlan``.
    """

    snapshot_date: str
    accounts: list[AccountSnapshot] = field(default_factory=list)
    holdings: list[HoldingSnapshot] = field(default_factory=list)
    missing_assumptions: list[str] = field(default_factory=list)

    def total_by_kind(self, kind: AccountKind) -> dict[Literal["EUR", "DKK"], Decimal]:
        """Sum account balances for *kind*, grouped by currency.

        Returns a dict with exactly two keys (``"EUR"`` and ``"DKK"``) even
        when one of the totals is zero.

        Args:
            kind: The account kind to filter on.

        Returns:
            ``{"EUR": <total>, "DKK": <total>}``
        """
        result: dict[Literal["EUR", "DKK"], Decimal] = {
            "EUR": Decimal("0"),
            "DKK": Decimal("0"),
        }
        for acc in self.accounts:
            if acc.kind == kind:
                result[acc.currency] += acc.balance
        return result

    def accounts_by_entity(self, entity_name: str) -> list[AccountSnapshot]:
        """Return all accounts owned by *entity_name*.

        Args:
            entity_name: Owner name to filter on (case-sensitive).

        Returns:
            Sub-list of :attr:`accounts`; empty list when no match.
        """
        return [a for a in self.accounts if a.entity_name == entity_name]

    def holdings_by_account(self, account_id: str) -> list[HoldingSnapshot]:
        """Return all holdings for *account_id*.

        Args:
            account_id: Account identifier to filter on.

        Returns:
            Sub-list of :attr:`holdings`; empty list when no match.
        """
        return [h for h in self.holdings if h.account_id == account_id]


class SnapshotBuilder:
    """Accumulate account and holding records and build a :class:`HouseholdSnapshot`.

    The builder validates each record as it is added and collects warnings
    in an internal list.  Call :meth:`build` once all records have been
    added.

    Example::

        from decimal import Decimal
        from penge.sim.snapshot import SnapshotBuilder

        snapshot = (
            SnapshotBuilder("2025-01-15")
            .add_account(
                account_id="acc-001",
                entity_name="lars",
                account_name="GLS lønkonto",
                kind="cash",
                currency="DKK",
                balance=Decimal("45000"),
                provider="gls",
                data_source="EnableBanking 2025-01-15",
            )
            .build()
        )

    Args:
        snapshot_date: ISO date string (``YYYY-MM-DD``) for the snapshot
            valuation date.
    """

    def __init__(self, snapshot_date: str) -> None:
        self._snapshot_date = snapshot_date
        self._accounts: list[AccountSnapshot] = []
        self._holdings: list[HoldingSnapshot] = []
        self._missing: list[str] = []

    # ------------------------------------------------------------------
    # Public builder methods
    # ------------------------------------------------------------------

    def add_account(
        self,
        *,
        account_id: str,
        entity_name: str,
        account_name: str,
        kind: str,
        currency: str,
        balance: Decimal | str,
        provider: str,
        data_source: str,
        notes: str = "",
    ) -> SnapshotBuilder:
        """Add a single account record to the snapshot.

        Validates *kind* and *currency*; unknown values are flagged in
        ``missing_assumptions`` and a safe fallback is applied so that
        processing can continue.

        Args:
            account_id: Stable identifier (external_id or DB UUID as string).
            entity_name: Owner name, e.g. ``"lars"``.
            account_name: Human-readable label.
            kind: Raw kind string from DB.  Must be one of the
                :data:`AccountKind` literals; if not, a warning is recorded
                and the kind falls back to ``"manual"``.
            currency: Raw currency string from DB.  Must be ``"EUR"`` or
                ``"DKK"``; otherwise a warning is recorded.
            balance: Current balance; accepts :class:`~decimal.Decimal` or
                any string accepted by ``Decimal()``.
            provider: Data provider slug.
            data_source: Provenance string.
            notes: Optional free-text annotation.

        Returns:
            ``self`` — supports method chaining.
        """
        resolved_kind = kind
        if kind not in _VALID_KINDS:
            self._missing.append(
                f"account {account_id!r} ({account_name!r}): "
                f"unrecognised kind {kind!r}; cannot determine tax treatment. "
                f"Set kind to one of {sorted(_VALID_KINDS)}"
            )
            logger.warning(
                "SnapshotBuilder: account %r has unknown kind %r; falling back to 'manual'",
                account_id,
                kind,
            )
            resolved_kind = "manual"

        if currency not in _VALID_CURRENCIES:
            self._missing.append(
                f"account {account_id!r} ({account_name!r}): "
                f"unsupported currency {currency!r}; only EUR and DKK are supported. "
                f"Account skipped — correct the currency and re-add it."
            )
            logger.warning(
                "SnapshotBuilder: account %r has unsupported currency %r; skipping",
                account_id,
                currency,
            )
            return self

        self._accounts.append(
            AccountSnapshot(
                account_id=account_id,
                entity_name=entity_name,
                account_name=account_name,
                kind=resolved_kind,  # type: ignore[arg-type]  # validated above
                currency=currency,  # type: ignore[arg-type]  # validated above
                balance=Decimal(str(balance)),
                provider=provider,
                data_source=data_source,
                notes=notes,
            )
        )
        return self

    def add_holding(
        self,
        *,
        account_id: str,
        isin: str,
        instrument_name: str,
        quantity: Decimal | str,
        market_value: Decimal | str,
        cost_basis: Decimal | str | None,
        currency: str,
        data_source: str,
    ) -> SnapshotBuilder:
        """Add a single holding record to the snapshot.

        Args:
            account_id: Matches an :class:`AccountSnapshot`'s ``account_id``.
            isin: ISIN of the instrument.
            instrument_name: Human-readable label.
            quantity: Units held; accepts :class:`~decimal.Decimal` or string.
            market_value: Current value in account currency.
            cost_basis: Total cost basis, or ``None`` if unknown (triggers a
                missing-assumption warning).
            currency: ``"EUR"`` or ``"DKK"``.
            data_source: Provenance string.

        Returns:
            ``self`` — supports method chaining.
        """
        if cost_basis is None:
            self._missing.append(
                f"holding {isin!r} in account {account_id!r}: "
                "cost_basis not available; "
                "bridge depletion calculation will be approximate"
            )
            logger.warning(
                "SnapshotBuilder: holding %r in account %r has no cost_basis",
                isin,
                account_id,
            )

        if currency not in _VALID_CURRENCIES:
            self._missing.append(
                f"holding {isin!r} in account {account_id!r}: unsupported currency {currency!r}. "
                f"Holding skipped — correct the currency and re-add it."
            )
            logger.warning(
                "SnapshotBuilder: holding %r in account %r has unsupported currency %r; skipping",
                isin,
                account_id,
                currency,
            )
            return self

        self._holdings.append(
            HoldingSnapshot(
                account_id=account_id,
                isin=isin,
                instrument_name=instrument_name,
                quantity=Decimal(str(quantity)),
                market_value=Decimal(str(market_value)),
                cost_basis=Decimal(str(cost_basis)) if cost_basis is not None else None,
                currency=currency,  # type: ignore[arg-type]  # validated above
                data_source=data_source,
            )
        )
        return self

    def build(self) -> HouseholdSnapshot:
        """Finalise and return the :class:`HouseholdSnapshot`.

        Returns:
            A new ``HouseholdSnapshot`` containing copies of all accumulated
            accounts, holdings, and missing-assumption warnings.
        """
        if self._missing:
            logger.info(
                "SnapshotBuilder: %d missing assumption(s) recorded",
                len(self._missing),
            )
        return HouseholdSnapshot(
            snapshot_date=self._snapshot_date,
            accounts=list(self._accounts),
            holdings=list(self._holdings),
            missing_assumptions=list(self._missing),
        )
