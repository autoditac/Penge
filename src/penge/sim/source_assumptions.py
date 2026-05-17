"""Reviewable planning assumptions extracted from parsed/OCR document text."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pydantic

from penge.sim._decimal_utils import to_decimal as _to_decimal

__all__ = [
    "ExtractedPlanningAssumption",
    "ParsedPlanningDocument",
    "PlanningAssumptionSource",
    "accept_planning_assumption",
    "accepted_assumptions",
    "extract_planning_assumptions",
    "reject_planning_assumption",
]

AssumptionKind = Literal[
    "pension_balance",
    "annuity_factor",
    "cost_basis",
    "annual_expense_ratio",
    "dividend_yield",
    "property_value",
    "mortgage_balance",
]
AssumptionStatus = Literal["suggested", "accepted", "rejected"]
Confidence = Literal["low", "medium", "high"]

_AMOUNT_PATTERN = r"(?P<value>[0-9][0-9., ]*)\s*(?P<unit>EUR|DKK|%|percent)?"
_PATTERNS: tuple[tuple[AssumptionKind, re.Pattern[str]], ...] = (
    (
        "pension_balance",
        re.compile(
            rf"\b(?:pension balance|pensionssaldo|pensionsformue)\b[:\s]+{_AMOUNT_PATTERN}", re.I
        ),
    ),
    (
        "annuity_factor",
        re.compile(
            rf"\b(?:annuity factor|livrente factor|annuitetsfaktor)\b[:\s]+{_AMOUNT_PATTERN}", re.I
        ),
    ),
    (
        "cost_basis",
        re.compile(rf"\b(?:cost basis|anskaffelsessum|kostpris)\b[:\s]+{_AMOUNT_PATTERN}", re.I),
    ),
    (
        "annual_expense_ratio",
        re.compile(rf"\b(?:aop|åop|ter|annual expense ratio)\b[:\s]+{_AMOUNT_PATTERN}", re.I),
    ),
    (
        "dividend_yield",
        re.compile(
            rf"\b(?:dividend yield|udbytteprocent|ausschüttungsrendite)\b[:\s]+{_AMOUNT_PATTERN}",
            re.I,
        ),
    ),
    (
        "property_value",
        re.compile(
            rf"\b(?:property value|home value|ejendomsværdi|immobilienwert)"
            rf"\b[:\s]+{_AMOUNT_PATTERN}",
            re.I,
        ),
    ),
    (
        "mortgage_balance",
        re.compile(
            rf"\b(?:mortgage balance|restgæld|realkreditgæld|darlehenssaldo)"
            rf"\b[:\s]+{_AMOUNT_PATTERN}",
            re.I,
        ),
    ),
)


class ParsedPlanningDocument(pydantic.BaseModel):
    """Parsed or OCR-extracted document text available for assumption extraction."""

    model_config = pydantic.ConfigDict(frozen=True)

    document_id: str
    path: Path
    text: str
    classification: str = "unknown"
    extracted_via: str = "unknown"


class PlanningAssumptionSource(pydantic.BaseModel):
    """Source provenance for one extracted planning assumption."""

    model_config = pydantic.ConfigDict(frozen=True)

    document_id: str
    path: Path
    classification: str
    extracted_via: str
    excerpt: str


class ExtractedPlanningAssumption(pydantic.BaseModel):
    """A suggested planning assumption that must be reviewed before use."""

    model_config = pydantic.ConfigDict(frozen=True)

    kind: AssumptionKind
    label: str
    value: Decimal
    unit: str
    confidence: Confidence
    status: AssumptionStatus = "suggested"
    source: PlanningAssumptionSource


def extract_planning_assumptions(
    documents: tuple[ParsedPlanningDocument, ...],
) -> tuple[ExtractedPlanningAssumption, ...]:
    """Extract reviewable planning assumptions from parsed/OCR document text.

    This function is deterministic and rule-based.
    It never sends document text to an LLM or external service.
    """

    assumptions: list[ExtractedPlanningAssumption] = []
    for document in documents:
        for kind, pattern in _PATTERNS:
            for match in pattern.finditer(document.text):
                source = PlanningAssumptionSource(
                    document_id=document.document_id,
                    path=document.path,
                    classification=document.classification,
                    extracted_via=document.extracted_via,
                    excerpt=_excerpt(document.text, match.start(), match.end()),
                )
                unit = _normalize_unit(match.group("unit"), kind)
                assumptions.append(
                    ExtractedPlanningAssumption(
                        kind=kind,
                        label=_label(kind),
                        value=_parse_value(match.group("value"), unit),
                        unit=unit,
                        confidence=_confidence(document.classification, kind),
                        source=source,
                    )
                )
    return tuple(assumptions)


def accept_planning_assumption(
    assumption: ExtractedPlanningAssumption,
) -> ExtractedPlanningAssumption:
    """Mark an extracted assumption as reviewed and accepted."""

    return assumption.model_copy(update={"status": "accepted"})


def reject_planning_assumption(
    assumption: ExtractedPlanningAssumption,
) -> ExtractedPlanningAssumption:
    """Mark an extracted assumption as reviewed and rejected."""

    return assumption.model_copy(update={"status": "rejected"})


def accepted_assumptions(
    assumptions: tuple[ExtractedPlanningAssumption, ...],
) -> tuple[ExtractedPlanningAssumption, ...]:
    """Return only assumptions explicitly accepted by the user."""

    return tuple(assumption for assumption in assumptions if assumption.status == "accepted")


def _parse_value(raw: str, unit: str) -> Decimal:
    normalized = raw.replace(" ", "")
    if "," in normalized and "." in normalized:
        if normalized.rfind(",") > normalized.rfind("."):
            normalized = normalized.replace(".", "").replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    elif normalized.count(".") > 1:
        normalized = normalized.replace(".", "")
    elif normalized.count(",") > 1:
        normalized = normalized.replace(",", "")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")
    value = _to_decimal(normalized)
    if unit == "%":
        return value / Decimal("100")
    return value


def _normalize_unit(unit: str | None, kind: AssumptionKind) -> str:
    if kind in {"annual_expense_ratio", "dividend_yield"}:
        return "%"
    return "DKK" if unit is None else unit.upper().replace("PERCENT", "%")


def _confidence(classification: str, kind: AssumptionKind) -> Confidence:
    relevant = {
        "pension_balance": {"pension", "pfa"},
        "annuity_factor": {"pension", "pfa"},
        "cost_basis": {"broker", "nordnet", "depot"},
        "annual_expense_ratio": {"broker", "nordnet", "pension", "pfa"},
        "dividend_yield": {"broker", "nordnet", "depot"},
        "property_value": {"real_estate", "mortgage"},
        "mortgage_balance": {"real_estate", "mortgage"},
    }
    if classification.lower() in relevant[kind]:
        return "high"
    if classification == "unknown":
        return "medium"
    return "low"


def _label(kind: AssumptionKind) -> str:
    return kind.replace("_", " ")


def _excerpt(text: str, start: int, end: int) -> str:
    prefix = max(start - 40, 0)
    suffix = min(end + 40, len(text))
    return " ".join(text[prefix:suffix].split())
