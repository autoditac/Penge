"""Tests for penge.sim.registry — assumption registry and audit record.

All tests use synthetic data only; no real personal data is used.
"""

from __future__ import annotations

import json

import pytest

from penge.sim.registry import (
    AssumptionEntry,
    ProjectionAuditRecord,
    build_standard_audit_record,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    name: str = "test rate",
    value: str = "5.0",
    unit: str = "%",
    source: str = "unit test",
    adr: str = "",
    notes: str = "",
) -> AssumptionEntry:
    return AssumptionEntry(
        name=name,
        value=value,
        unit=unit,
        source=source,
        adr=adr,
        notes=notes,
    )


def _make_record(run_id: str = "test-run") -> ProjectionAuditRecord:
    return ProjectionAuditRecord(
        run_id=run_id,
        captured_at="2025-01-01T00:00:00+00:00",
        penge_version="0.0.0",
        assumptions=[_make_entry()],
    )


# ---------------------------------------------------------------------------
# AssumptionEntry
# ---------------------------------------------------------------------------


class TestAssumptionEntry:
    def test_fields_stored(self) -> None:
        e = AssumptionEntry(
            name="DK ASK rate",
            value="17",
            unit="%",
            source="SKAT 2025",
            adr="ADR-0027",
            notes="flat lager rate",
        )
        assert e.name == "DK ASK rate"
        assert e.value == "17"
        assert e.unit == "%"
        assert e.source == "SKAT 2025"
        assert e.adr == "ADR-0027"
        assert e.notes == "flat lager rate"

    def test_optional_fields_default_to_empty_string(self) -> None:
        e = AssumptionEntry(name="x", value="1", unit="unit", source="src")
        assert e.adr == ""
        assert e.notes == ""


# ---------------------------------------------------------------------------
# ProjectionAuditRecord — construction and add()
# ---------------------------------------------------------------------------


class TestProjectionAuditRecord:
    def test_add_appends_entry(self) -> None:
        record = _make_record()
        initial_count = len(record.assumptions)
        record.add(_make_entry(name="extra"))
        assert len(record.assumptions) == initial_count + 1
        assert record.assumptions[-1].name == "extra"

    def test_add_multiple_entries(self) -> None:
        record = ProjectionAuditRecord(
            run_id="r", captured_at="2025-01-01T00:00:00+00:00", penge_version="0"
        )
        for i in range(5):
            record.add(_make_entry(name=f"entry-{i}"))
        assert len(record.assumptions) == 5

    # ── to_json ──────────────────────────────────────────────────────────────

    def test_to_json_is_valid_json(self) -> None:
        record = _make_record()
        data = record.to_json()
        parsed = json.loads(data)
        assert isinstance(parsed, dict)

    def test_to_json_contains_required_keys(self) -> None:
        record = _make_record()
        parsed = json.loads(record.to_json())
        assert "run_id" in parsed
        assert "captured_at" in parsed
        assert "penge_version" in parsed
        assert "assumptions" in parsed

    def test_to_json_assumptions_is_list(self) -> None:
        record = _make_record()
        parsed = json.loads(record.to_json())
        assert isinstance(parsed["assumptions"], list)

    def test_to_json_entry_keys(self) -> None:
        record = _make_record()
        parsed = json.loads(record.to_json())
        entry = parsed["assumptions"][0]
        assert set(entry.keys()) == {"name", "value", "unit", "source", "adr", "notes"}

    # ── to_markdown ──────────────────────────────────────────────────────────

    def test_to_markdown_starts_with_h1(self) -> None:
        record = _make_record(run_id="my-run")
        md = record.to_markdown()
        assert md.startswith("# Projection audit: my-run")

    def test_to_markdown_contains_table_header(self) -> None:
        record = _make_record()
        md = record.to_markdown()
        assert "| Assumption | Value | Unit | Source | ADR | Notes |" in md

    def test_to_markdown_contains_entry_values(self) -> None:
        record = ProjectionAuditRecord(
            run_id="r",
            captured_at="2025-01-01T00:00:00+00:00",
            penge_version="0",
            assumptions=[AssumptionEntry(name="My rate", value="99", unit="%", source="my source")],
        )
        md = record.to_markdown()
        assert "My rate" in md
        assert "99" in md
        assert "my source" in md

    def test_to_markdown_contains_version(self) -> None:
        record = _make_record()
        assert "0.0.0" in record.to_markdown()

    # ── from_json round-trip ─────────────────────────────────────────────────

    def test_from_json_round_trip(self) -> None:
        original = _make_record()
        restored = ProjectionAuditRecord.from_json(original.to_json())
        assert restored.run_id == original.run_id
        assert restored.captured_at == original.captured_at
        assert restored.penge_version == original.penge_version
        assert len(restored.assumptions) == len(original.assumptions)

    def test_from_json_entry_fields_preserved(self) -> None:
        e = AssumptionEntry(
            name="DK PAL-skat",
            value="15.3",
            unit="%",
            source="SKAT 2025",
            adr="ADR-0013",
            notes="withheld by PFA",
        )
        record = ProjectionAuditRecord(
            run_id="x",
            captured_at="2025-01-01T00:00:00+00:00",
            penge_version="0",
            assumptions=[e],
        )
        restored = ProjectionAuditRecord.from_json(record.to_json())
        r_entry = restored.assumptions[0]
        assert r_entry.name == e.name
        assert r_entry.value == e.value
        assert r_entry.unit == e.unit
        assert r_entry.source == e.source
        assert r_entry.adr == e.adr
        assert r_entry.notes == e.notes

    def test_from_json_multiple_entries(self) -> None:
        record = ProjectionAuditRecord(
            run_id="r",
            captured_at="2025-01-01T00:00:00+00:00",
            penge_version="0",
        )
        for i in range(3):
            record.add(_make_entry(name=f"entry-{i}", value=str(i)))
        restored = ProjectionAuditRecord.from_json(record.to_json())
        assert len(restored.assumptions) == 3
        for i, entry in enumerate(restored.assumptions):
            assert entry.name == f"entry-{i}"
            assert entry.value == str(i)

    def test_from_json_invalid_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            ProjectionAuditRecord.from_json("not json")

    def test_from_json_assumptions_not_list_raises(self) -> None:
        record = _make_record()
        d = json.loads(record.to_json())
        d["assumptions"] = "not-a-list"
        with pytest.raises(ValueError, match="JSON array"):
            ProjectionAuditRecord.from_json(json.dumps(d))

    def test_from_json_assumption_not_dict_raises(self) -> None:
        record = _make_record()
        d = json.loads(record.to_json())
        d["assumptions"] = [42]
        with pytest.raises(ValueError, match="JSON object"):
            ProjectionAuditRecord.from_json(json.dumps(d))

    def test_from_json_numeric_values_coerced_to_str(self) -> None:
        """JSON with numeric value fields must be coerced to str round-trip."""
        record = _make_record()
        d = json.loads(record.to_json())
        # Simulate a JSON file where 'value' was stored as a number
        d["assumptions"][0]["value"] = 15.3
        restored = ProjectionAuditRecord.from_json(json.dumps(d))
        assert isinstance(restored.assumptions[0].value, str)

    def test_to_markdown_escapes_pipe_in_fields(self) -> None:
        entry = AssumptionEntry(
            name="rate|check",
            value="10",
            unit="%",
            source="test|src",
            notes="a|b",
        )
        record = ProjectionAuditRecord(
            run_id="r",
            captured_at="2025-01-01T00:00:00+00:00",
            penge_version="0",
            assumptions=[entry],
        )
        md = record.to_markdown()
        # Raw pipes inside values must be escaped so the table stays valid
        assert "rate\\|check" in md
        assert "test\\|src" in md
        assert "a\\|b" in md

    def test_to_markdown_escapes_newlines_in_fields(self) -> None:
        entry = AssumptionEntry(
            name="rate",
            value="10",
            unit="%",
            source="src",
            notes="line1\nline2",
        )
        record = ProjectionAuditRecord(
            run_id="r",
            captured_at="2025-01-01T00:00:00+00:00",
            penge_version="0",
            assumptions=[entry],
        )
        md = record.to_markdown()
        # The notes row must not contain a bare newline inside the table
        table_lines = [ln for ln in md.splitlines() if "line1" in ln]
        assert table_lines, "entry row not found in markdown output"
        assert "\n" not in table_lines[0]
        assert "line1 line2" in table_lines[0]


# ---------------------------------------------------------------------------
# build_standard_audit_record
# ---------------------------------------------------------------------------


class TestBuildStandardAuditRecord:
    def test_returns_projection_audit_record(self) -> None:
        record = build_standard_audit_record()
        assert isinstance(record, ProjectionAuditRecord)

    def test_has_at_least_five_assumptions(self) -> None:
        record = build_standard_audit_record()
        assert len(record.assumptions) >= 5

    def test_run_id_defaults_to_nonempty(self) -> None:
        record = build_standard_audit_record()
        assert record.run_id
        assert len(record.run_id) > 0

    def test_run_id_custom_is_used(self) -> None:
        record = build_standard_audit_record(run_id="my-label")
        assert record.run_id == "my-label"

    def test_penge_version_is_nonempty_string(self) -> None:
        record = build_standard_audit_record()
        assert isinstance(record.penge_version, str)
        assert len(record.penge_version) > 0

    def test_captured_at_is_nonempty(self) -> None:
        record = build_standard_audit_record()
        assert record.captured_at
        assert "T" in record.captured_at  # ISO 8601 contains "T"

    def test_all_entries_have_required_fields(self) -> None:
        record = build_standard_audit_record()
        for entry in record.assumptions:
            assert entry.name, f"empty name in entry: {entry}"
            assert entry.value, f"empty value in entry: {entry}"
            assert entry.unit, f"empty unit in entry: {entry}"
            assert entry.source, f"empty source in entry: {entry}"

    def test_extra_entries_are_included(self) -> None:
        extra = AssumptionEntry(
            name="Portfolio expected return",
            value="5.5",
            unit="%",
            source="user input",
        )
        record = build_standard_audit_record(extra_entries=[extra])
        names = [e.name for e in record.assumptions]
        assert "Portfolio expected return" in names

    def test_extra_entries_appended_after_standard(self) -> None:
        extra = AssumptionEntry(
            name="FX EUR/DKK",
            value="7.46",
            unit="DKK/EUR",
            source="ECB",
        )
        record = build_standard_audit_record(extra_entries=[extra])
        assert record.assumptions[-1].name == "FX EUR/DKK"

    def test_multiple_extra_entries(self) -> None:
        extras = [
            AssumptionEntry(name=f"extra-{i}", value=str(i), unit="x", source="test")
            for i in range(3)
        ]
        record = build_standard_audit_record(extra_entries=extras)
        names = [e.name for e in record.assumptions]
        for i in range(3):
            assert f"extra-{i}" in names

    def test_to_json_round_trips(self) -> None:
        record = build_standard_audit_record(run_id="rt-test")
        restored = ProjectionAuditRecord.from_json(record.to_json())
        assert restored.run_id == record.run_id
        assert len(restored.assumptions) == len(record.assumptions)

    def test_to_markdown_starts_with_h1(self) -> None:
        record = build_standard_audit_record(run_id="audit-run")
        assert record.to_markdown().startswith("# Projection audit: audit-run")

    def test_to_markdown_contains_table_header(self) -> None:
        record = build_standard_audit_record()
        md = record.to_markdown()
        assert "| Assumption | Value | Unit | Source | ADR | Notes |" in md

    def test_dk_pal_skat_entry_present(self) -> None:
        record = build_standard_audit_record()
        names = [e.name for e in record.assumptions]
        assert any("PAL" in n for n in names)

    def test_ask_rate_entry_present(self) -> None:
        record = build_standard_audit_record()
        names = [e.name for e in record.assumptions]
        assert any("ASK" in n for n in names)

    def test_ask_cap_entry_present(self) -> None:
        record = build_standard_audit_record()
        names = [e.name for e in record.assumptions]
        assert any("cap" in n.lower() for n in names)

    def test_de_abgeltungsteuer_entry_present(self) -> None:
        record = build_standard_audit_record()
        names = [e.name for e in record.assumptions]
        assert any("Abgeltungsteuer" in n for n in names)

    def test_lager_low_rate_entry_present(self) -> None:
        record = build_standard_audit_record()
        names = [e.name for e in record.assumptions]
        assert any("Lager" in n and "low" in n.lower() for n in names)

    def test_lager_threshold_entry_present(self) -> None:
        record = build_standard_audit_record()
        names = [e.name for e in record.assumptions]
        assert any("threshold" in n.lower() for n in names)

    def test_serialised_json_is_valid(self) -> None:
        record = build_standard_audit_record()
        data = json.loads(record.to_json())
        assert data["run_id"]
        assert isinstance(data["assumptions"], list)
        assert len(data["assumptions"]) >= 5
