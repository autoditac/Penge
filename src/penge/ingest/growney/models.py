"""Pydantic models for parsed Sutor Depotauszug records."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", strict=False)


class ParsedHolding(_Frozen):
    """One row of the Sutor "Aufstellung über Kundenfinanzinstrumente" table.

    ``market_value_eur`` is denominated in EUR even when the unit
    price (``price``) and ``price_currency`` are USD; Sutor always
    expresses ``Kurswert`` in the depot's basisvaluta (EUR for
    Growney).
    """

    name: str = Field(..., description="Investment / fund name as printed.")
    isin: str = Field(..., description="12-character ISIN.")
    lagerstelle: str | None = Field(None, description="e.g. 'Deutschland' / 'Irland'.")
    verwahrart: str | None = Field(
        None, description="e.g. 'Girosammelverwahrung' / 'Wertpapierrechnung'."
    )
    allocation_pct: Decimal | None = Field(
        None, description="Anlagequote (%), 0..100. None for cash sub-balance."
    )
    quantity: Decimal = Field(..., description="Bestand (units).")
    unit: str = Field(..., description="e.g. 'Anteile' or 'Stück'.")
    price: Decimal | None = Field(None, description="Kurs per unit, in price_currency.")
    price_currency: str = Field(..., description="Currency of the unit price (EUR or USD).")
    market_value_eur: Decimal = Field(..., description="Kurswert in EUR.")


class ParsedTransaction(_Frozen):
    """One row of the Sutor "Umsätze" table.

    Sutor exports do not include a stable transaction id, so the
    loader synthesizes one via :func:`synthesize_external_id`.
    """

    bookkeeping_date: date = Field(..., description="Buchungsdatum.")
    value_date: date = Field(..., description="Wertstellung.")
    kind: str = Field(..., description="Canonical kind from constants.py.")
    sutor_type: str = Field(..., description="Raw 'Transaktion' column value.")
    venue: str | None = Field(None, description="Handelsplatz, e.g. 'Tradegate'.")
    description: str | None = Field(None, description="Free-text 'Umsatz / Finanz-Instrument'.")
    isin: str | None = Field(None, description="ISIN where the row references a security.")
    quantity: Decimal | None = Field(None, description="Anteile / Gramm.")
    unit_price: Decimal | None = Field(None, description="Kurs / Preis (in unit_price_currency).")
    unit_price_currency: str | None = Field(
        None, description="Currency of the unit price (EUR or USD)."
    )
    fx_rate: Decimal | None = Field(None, description="W-Kurs (EUR per unit_price_currency).")
    gross_amount_eur: Decimal | None = Field(None, description="Betrag (brutto), in EUR.")
    net_amount_eur: Decimal = Field(..., description="Betrag (netto), in EUR (signed).")
    fees_eur: Decimal | None = Field(None, description="Kosten, in EUR.")
    capital_tax_eur: Decimal | None = Field(None, description="KESt + SolZ combined, in EUR.")
    church_tax_eur: Decimal | None = Field(None, description="KiSt, in EUR.")


class ParsedDepotauszug(_Frozen):
    """The fully parsed contents of one Sutor Depotauszug PDF."""

    depot_number: str = Field(..., description="Sutor 10-digit Depotnummer.")
    iban: str | None = Field(None, description="IBAN as printed on the cover sheet.")
    strategy: str | None = Field(
        None, description='growney strategy name from the inner header (e.g. "growgreen100").'
    )
    as_of: date = Field(..., description="Snapshot date from the holdings header.")
    period_from: date | None = Field(None, description="Start of Umsätze period.")
    period_to: date | None = Field(None, description="End of Umsätze period.")
    holdings: tuple[ParsedHolding, ...] = Field(default_factory=tuple)
    transactions: tuple[ParsedTransaction, ...] = Field(default_factory=tuple)
    cash_balance_eur: Decimal = Field(
        default=Decimal("0"), description="Geldsaldo at as_of, in EUR."
    )
