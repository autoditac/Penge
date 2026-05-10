"""Tax-lot tracker for realisationsbeskattede instruments (issue #35, ADR-0016).

Implements the Danish *gennemsnitsmetoden* — average-cost method per
``(account_id, isin)``. The book holds a single aggregated lot per pair;
purchases blend in at the new price, sales reduce the quantity at the
running average cost (and produce a realised gain/loss), splits and
mergers adjust quantity in inverse proportion to the share-ratio so the
total cost-basis is preserved.

Public API
----------

- :class:`Money`  — opaque ``(amount, currency)`` pair (Decimal).
- :class:`TaxLot` — frozen view of one ``(account_id, isin)`` aggregate.
- :class:`Buy`, :class:`Sell`, :class:`Split`, :class:`Merge` —
  immutable event records that drive the book.
- :class:`LotBook` — the in-memory store; replays events in order.
- :class:`RealisedGain` — output record for each :class:`Sell`.
- :exc:`LotError` — raised on semantic violations (oversell, currency
  mismatch, …).

The book is *deterministic*: feeding the same event sequence always
produces the same lots and gains, and quantities round to 6 decimal
places (sufficient for fractional shares) while monetary amounts round
to 2 decimal places using ``ROUND_HALF_EVEN``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date as _date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Annotated, Literal

import pydantic
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "Buy",
    "LotBook",
    "LotError",
    "Merge",
    "Money",
    "RealisedGain",
    "Sell",
    "Split",
    "TaxLot",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_QTY_DP = Decimal("0.000001")  # six decimals for fractional shares
_MONEY_DP = Decimal("0.01")
_ZERO = Decimal("0")
Currency = Literal["EUR", "DKK"]


def _q_qty(value: Decimal) -> Decimal:
    return value.quantize(_QTY_DP, rounding=ROUND_HALF_EVEN)


def _q_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_DP, rounding=ROUND_HALF_EVEN)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LotError(Exception):
    """Raised when an event would put the book in an inconsistent state."""


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


class Money(BaseModel):
    """A typed ``(amount, currency)`` pair.

    Stored in the original transaction currency; the lot book never
    converts. Mixing currencies on the same ``(account_id, isin)`` is
    rejected by the book.
    """

    model_config = ConfigDict(frozen=True, strict=False)

    amount: Decimal
    currency: Currency

    @field_validator("amount")
    @classmethod
    def _finite(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError("amount must be a finite Decimal")
        return _q_money(v)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class _EventBase(BaseModel):
    model_config = ConfigDict(frozen=True, strict=False)

    event_date: _date
    account_id: str = Field(min_length=1)
    isin: Annotated[str, Field(min_length=12, max_length=12)]


class Buy(_EventBase):
    """Purchase of ``quantity`` shares at ``price`` per share, plus ``fee``.

    Cost basis added to the lot is ``quantity * price + fee``. The lot's
    average cost per share is recomputed after the addition.
    """

    kind: Literal["buy"] = "buy"
    quantity: Decimal
    price: Money
    fee: Money | None = None

    @field_validator("quantity")
    @classmethod
    def _positive_qty(cls, v: Decimal) -> Decimal:
        if not v.is_finite() or v <= 0:
            raise ValueError("quantity must be a finite, strictly positive Decimal")
        return _q_qty(v)

    @model_validator(mode="after")
    def _currency_match(self) -> Buy:
        if self.fee is not None and self.fee.currency != self.price.currency:
            raise ValueError("fee currency must match price currency")
        return self


class Sell(_EventBase):
    """Disposal of ``quantity`` shares at ``price`` per share, less ``fee``.

    The realised gain (gross of any tax overlay) equals
    ``quantity * (price - avg_cost) - fee``.
    """

    kind: Literal["sell"] = "sell"
    quantity: Decimal
    price: Money
    fee: Money | None = None

    @field_validator("quantity")
    @classmethod
    def _positive_qty(cls, v: Decimal) -> Decimal:
        if not v.is_finite() or v <= 0:
            raise ValueError("quantity must be a finite, strictly positive Decimal")
        return _q_qty(v)

    @model_validator(mode="after")
    def _currency_match(self) -> Sell:
        if self.fee is not None and self.fee.currency != self.price.currency:
            raise ValueError("fee currency must match price currency")
        return self


class Split(_EventBase):
    """Stock split adjusting quantity by ``ratio`` (new = old * ratio).

    Cost basis is unchanged; the average cost per share scales by
    ``1 / ratio``. ``ratio == 2`` is a 2-for-1 split; ``ratio == Decimal("0.5")``
    is a 1-for-2 reverse split.
    """

    kind: Literal["split"] = "split"
    ratio: Decimal

    @field_validator("ratio")
    @classmethod
    def _positive_ratio(cls, v: Decimal) -> Decimal:
        if not v.is_finite() or v <= 0:
            raise ValueError("ratio must be a finite, strictly positive Decimal")
        return v


class Merge(_EventBase):
    """Issuer merger that replaces the existing lot with shares of ``new_isin``.

    ``share_ratio`` shares of ``new_isin`` are issued for every share of
    ``isin``. Total cost basis is preserved; the lot keyed by ``isin``
    is removed and a lot keyed by ``new_isin`` is created (or merged into
    if it already exists, blending at the running average cost).
    """

    kind: Literal["merge"] = "merge"
    new_isin: Annotated[str, Field(min_length=12, max_length=12)]
    share_ratio: Decimal

    @field_validator("share_ratio")
    @classmethod
    def _positive_ratio(cls, v: Decimal) -> Decimal:
        if not v.is_finite() or v <= 0:
            raise ValueError("share_ratio must be a finite, strictly positive Decimal")
        return v


Event = Buy | Sell | Split | Merge


# ---------------------------------------------------------------------------
# Output records
# ---------------------------------------------------------------------------


class TaxLot(BaseModel):
    """Aggregate position for ``(account_id, isin)`` under gennemsnitsmetoden.

    ``avg_cost`` is the cost basis per share (cost / quantity) at the
    quantity precision of :data:`_QTY_DP`. ``cost_basis`` is the
    monetary aggregate.
    """

    model_config = ConfigDict(frozen=True, strict=False)

    account_id: str
    isin: str
    quantity: Decimal
    cost_basis: Money

    @property
    def avg_cost(self) -> Decimal:
        if self.quantity == _ZERO:
            return _ZERO
        return _q_money(self.cost_basis.amount / self.quantity)


class RealisedGain(BaseModel):
    """One realisation event produced by a :class:`Sell`."""

    model_config = ConfigDict(frozen=True, strict=False)

    event_date: _date
    account_id: str
    isin: str
    quantity: Decimal
    proceeds: Money
    cost_basis: Money
    gain: Money

    @model_validator(mode="after")
    def _consistent_currencies(self) -> RealisedGain:
        if not (self.proceeds.currency == self.cost_basis.currency == self.gain.currency):
            raise ValueError("proceeds, cost_basis, gain must share a currency")
        return self


# ---------------------------------------------------------------------------
# Book
# ---------------------------------------------------------------------------


class _MutableLot:
    __slots__ = ("account_id", "cost", "currency", "isin", "quantity")

    def __init__(
        self,
        account_id: str,
        isin: str,
        quantity: Decimal,
        cost: Decimal,
        currency: Currency,
    ) -> None:
        self.account_id = account_id
        self.isin = isin
        self.quantity = quantity
        self.cost = cost
        self.currency: Currency = currency

    def snapshot(self) -> TaxLot:
        return TaxLot(
            account_id=self.account_id,
            isin=self.isin,
            quantity=_q_qty(self.quantity),
            cost_basis=Money(amount=_q_money(self.cost), currency=self.currency),
        )


class LotBook:
    """In-memory tax-lot ledger.

    Apply events in chronological order (the book itself does not sort
    — feed events sorted by ``event_date`` to preserve audit semantics).

    The book is intentionally not a Pydantic model: it is a mutable
    aggregate over immutable events. Snapshot it via :meth:`lots` to get
    a frozen view, or via :meth:`realised_gains` to read out the audit
    trail.
    """

    def __init__(self) -> None:
        self._lots: dict[tuple[str, str], _MutableLot] = {}
        self._realised: list[RealisedGain] = []

    # -- mutators ------------------------------------------------------

    def apply(self, event: Event) -> None:
        if isinstance(event, Buy):
            self._apply_buy(event)
        elif isinstance(event, Sell):
            self._apply_sell(event)
        elif isinstance(event, Split):
            self._apply_split(event)
        elif isinstance(event, Merge):
            self._apply_merge(event)
        else:  # pragma: no cover - exhaustive over Event union
            raise LotError(f"unknown event type: {type(event).__name__}")

    def apply_all(self, events: Iterable[Event]) -> None:
        for ev in events:
            self.apply(ev)

    def _apply_buy(self, ev: Buy) -> None:
        key = (ev.account_id, ev.isin)
        cost_added = ev.quantity * ev.price.amount + (
            ev.fee.amount if ev.fee is not None else _ZERO
        )
        if key in self._lots:
            lot = self._lots[key]
            if lot.currency != ev.price.currency:
                raise LotError(
                    f"currency mismatch for {ev.isin} on {ev.account_id}: "
                    f"existing {lot.currency} vs incoming {ev.price.currency}"
                )
            lot.quantity = lot.quantity + ev.quantity
            lot.cost = lot.cost + cost_added
        else:
            self._lots[key] = _MutableLot(
                account_id=ev.account_id,
                isin=ev.isin,
                quantity=ev.quantity,
                cost=cost_added,
                currency=ev.price.currency,
            )

    def _apply_sell(self, ev: Sell) -> None:
        key = (ev.account_id, ev.isin)
        if key not in self._lots:
            raise LotError(
                f"cannot sell {ev.isin} on {ev.account_id}: no open lot",
            )
        lot = self._lots[key]
        if lot.currency != ev.price.currency:
            raise LotError(
                f"currency mismatch for {ev.isin} on {ev.account_id}: "
                f"existing {lot.currency} vs incoming {ev.price.currency}",
            )
        # tolerate tiny float-ish noise: oversell only if strictly greater
        if ev.quantity > lot.quantity + _QTY_DP:
            raise LotError(
                f"cannot sell {ev.quantity} of {ev.isin} on {ev.account_id}: "
                f"only {lot.quantity} available",
            )
        sold_qty = min(ev.quantity, lot.quantity)
        avg = lot.cost / lot.quantity if lot.quantity > 0 else _ZERO
        cost_removed = avg * sold_qty
        fee = ev.fee.amount if ev.fee is not None else _ZERO
        proceeds = sold_qty * ev.price.amount - fee
        gain = proceeds - cost_removed
        lot.quantity = lot.quantity - sold_qty
        lot.cost = lot.cost - cost_removed
        if lot.quantity <= _QTY_DP:
            # close out residual rounding dust
            lot.quantity = _ZERO
            lot.cost = _ZERO
            del self._lots[key]
        currency: Currency = ev.price.currency
        self._realised.append(
            RealisedGain(
                event_date=ev.event_date,
                account_id=ev.account_id,
                isin=ev.isin,
                quantity=_q_qty(sold_qty),
                proceeds=Money(amount=_q_money(proceeds), currency=currency),
                cost_basis=Money(amount=_q_money(cost_removed), currency=currency),
                gain=Money(amount=_q_money(gain), currency=currency),
            )
        )

    def _apply_split(self, ev: Split) -> None:
        key = (ev.account_id, ev.isin)
        if key not in self._lots:
            raise LotError(
                f"cannot split {ev.isin} on {ev.account_id}: no open lot",
            )
        lot = self._lots[key]
        lot.quantity = lot.quantity * ev.ratio
        # cost unchanged; avg_cost = cost / (qty * ratio) = old_avg / ratio.

    def _apply_merge(self, ev: Merge) -> None:
        old_key = (ev.account_id, ev.isin)
        if old_key not in self._lots:
            raise LotError(
                f"cannot merge {ev.isin} on {ev.account_id}: no open lot",
            )
        old = self._lots.pop(old_key)
        new_qty = old.quantity * ev.share_ratio
        new_key = (ev.account_id, ev.new_isin)
        if new_key in self._lots:
            target = self._lots[new_key]
            if target.currency != old.currency:
                raise LotError(
                    f"currency mismatch when merging {ev.isin} into {ev.new_isin}: "
                    f"{old.currency} vs {target.currency}",
                )
            target.quantity = target.quantity + new_qty
            target.cost = target.cost + old.cost
        else:
            self._lots[new_key] = _MutableLot(
                account_id=ev.account_id,
                isin=ev.new_isin,
                quantity=new_qty,
                cost=old.cost,
                currency=old.currency,
            )

    # -- queries -------------------------------------------------------

    def lots(self) -> Mapping[tuple[str, str], TaxLot]:
        """Return a frozen snapshot keyed by ``(account_id, isin)``."""
        return {k: v.snapshot() for k, v in self._lots.items()}

    def lot(self, account_id: str, isin: str) -> TaxLot | None:
        ml = self._lots.get((account_id, isin))
        return ml.snapshot() if ml is not None else None

    def realised_gains(self) -> tuple[RealisedGain, ...]:
        """Audit trail of all :class:`Sell` events applied so far."""
        return tuple(self._realised)

    def total_quantity(self, account_id: str, isin: str) -> Decimal:
        """Sum of lot quantities for the pair (always equals the lot quantity).

        Provided as a property-test invariant target: the book maintains
        a single aggregate lot per pair, so this always equals
        ``self.lot(account_id, isin).quantity`` (or 0 if no lot).
        """
        ml = self._lots.get((account_id, isin))
        return _q_qty(ml.quantity) if ml is not None else _ZERO


# Re-export for type checkers that don't follow union aliases.
_ = pydantic.BaseModel  # silence unused-import linters in some setups
