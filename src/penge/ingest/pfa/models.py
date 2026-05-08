"""Pydantic models for parsed PFA Pensionsoversigt records.

All money fields are denominated in DKK; PFA does not report
in any other currency on the consumer statement.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", strict=False)


class ParsedHolding(_Frozen):
    """One row of the policy's investment-profile fund breakdown.

    PFA Plus funds are not exchange-listed so ``isin`` is always
    ``None`` here; the loader synthesises an ``instrument.ticker``
    of the form ``PFA:<slug>`` to give the row a stable identity.
    """

    fund_name: str = Field(..., description="Fund name as printed on the PDF.")
    allocation_pct: Decimal | None = Field(
        None, description="Andel of the policy (0..100), if printed."
    )
    quantity: Decimal | None = Field(
        None,
        description="Units (Andele). PFA omits this for some legacy profiles.",
    )
    market_value_dkk: Decimal = Field(..., description="Market value in DKK at as_of.")


class ParsedContribution(_Frozen):
    """A single contribution line, split by source.

    PFA aggregates contributions on the statement; this model
    captures one *source* (employer or employee) summed over the
    statement period. The loader posts one ``deposit`` transaction
    per source, dated on ``period_to`` (PFA does not break out
    individual transfer dates on the consumer statement).
    """

    source: str = Field(..., description='"employer" or "employee".')
    amount_dkk: Decimal = Field(..., description="Total contribution in DKK over the period.")


class ParsedScheme(_Frozen):
    """One pension sub-policy within a Pensionsoversigt PDF.

    A single PFA policy holder typically has 1-3 schemes
    (aldersopsparing + ratepension + livrente are the common mix).
    Each scheme has its own balance, return, fees, and PAL-skat
    line, so each maps to a distinct ``account`` row in Penge.
    """

    scheme_kind: str = Field(
        ...,
        description="Canonical kind from constants.py: "
        "aldersopsparing / ratepension / livrente.",
    )
    sub_policy_id: str = Field(
        ...,
        description="Suffix used to disambiguate this scheme inside the policy "
        "(e.g. 'A', 'R', 'L', or PFA's own internal numeric suffix).",
    )
    opening_balance_dkk: Decimal = Field(..., description="Balance at period_from.")
    closing_balance_dkk: Decimal = Field(..., description="Balance at period_to.")
    contributions: tuple[ParsedContribution, ...] = Field(default_factory=tuple)
    return_dkk: Decimal = Field(
        Decimal("0"),
        description="Gross investment return credited over the period (positive=gain).",
    )
    fees_dkk: Decimal = Field(
        Decimal("0"), description="Administration / investment fees deducted (positive)."
    )
    pal_skat_dkk: Decimal = Field(
        Decimal("0"),
        description="PAL-skat (15.3%) deducted on the return (positive=tax paid).",
    )
    holdings: tuple[ParsedHolding, ...] = Field(
        default_factory=tuple,
        description="Investment-profile fund breakdown at period_to.",
    )


class ParsedPensionsoversigt(_Frozen):
    """The fully parsed contents of one PFA Pensionsoversigt PDF."""

    policy_number: str = Field(..., description="PFA policy number as printed.")
    as_of: date = Field(..., description="Snapshot date from the cover sheet.")
    period_from: date | None = Field(
        None, description="Start of the reported period (Optjeningsperiode start)."
    )
    period_to: date | None = Field(None, description="End of the reported period.")
    schemes: tuple[ParsedScheme, ...] = Field(default_factory=tuple)
    extracted_via: str = Field(
        "pdfplumber",
        description="'pdfplumber' or 'ocr' — which extraction path produced this record.",
    )
