"""Tests for document-backed planning assumption extraction."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from penge.sim.source_assumptions import (
    ParsedPlanningDocument,
    accept_planning_assumption,
    accepted_assumptions,
    extract_planning_assumptions,
    reject_planning_assumption,
)


def test_extract_planning_assumptions_keeps_source_provenance_and_review_state() -> None:
    document = ParsedPlanningDocument(
        document_id="synthetic-pfa-2026",
        path=Path("synthetic/pfa-2026.txt"),
        classification="pfa",
        extracted_via="ocr",
        text=(
            "Pensionssaldo: 1.200.000 EUR\n"
            "Annuity factor: 4800\n"
            "ÅOP: 0,45%\n"
            "Cost basis: 250000 DKK\n"
            "Dividend yield: 2.5%\n"
            "Property value: 4,000,000 DKK\n"
            "Mortgage balance: 2,500,000 DKK\n"
        ),
    )

    assumptions = extract_planning_assumptions((document,))
    by_kind = {assumption.kind: assumption for assumption in assumptions}
    accepted = accept_planning_assumption(by_kind["pension_balance"])
    rejected = reject_planning_assumption(by_kind["annuity_factor"])

    assert by_kind["pension_balance"].value == Decimal("1200000")
    assert by_kind["annual_expense_ratio"].value == Decimal("0.0045")
    assert by_kind["property_value"].source.document_id == "synthetic-pfa-2026"
    assert by_kind["property_value"].status == "suggested"
    assert accepted.status == "accepted"
    assert rejected.status == "rejected"
    assert accepted_assumptions((accepted, rejected)) == (accepted,)
