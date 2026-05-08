"""Pure-parser tests for the ABIS list ingestor."""

from __future__ import annotations

import codecs
from pathlib import Path

import pytest

from penge.tax.abis import (
    ABIS_PLACEHOLDER,
    DK_TAX_LAGERBESKATNING,
    DK_TAX_REALISATION,
    SOURCE_ABIS,
    SOURCE_MANUAL,
    parse_abis_csv,
    parse_year_set,
)
from penge.tax.abis.loader import _records_to_observations
from tests.tax.abis.fixtures import ABIS_CSV_FIXTURE_TEXT


@pytest.fixture  # type: ignore[untyped-decorator]
def fixture_csv(tmp_path: Path) -> Path:
    p = tmp_path / "abis.csv"
    # Prepend a UTF-8 BOM so utf-8-sig handling is exercised.
    p.write_bytes(codecs.BOM_UTF8 + ABIS_CSV_FIXTURE_TEXT.encode("utf-8"))
    return p


def test_constants_are_what_callers_expect() -> None:
    assert DK_TAX_LAGERBESKATNING == "lagerbeskatning"
    assert DK_TAX_REALISATION == "realisation"
    assert SOURCE_ABIS == "abis"
    assert SOURCE_MANUAL == "manual"
    assert ABIS_PLACEHOLDER == "[tom]"


@pytest.mark.parametrize(  # type: ignore[untyped-decorator]
    ("raw", "expected"),
    [
        ("", frozenset()),
        ("[tom]", frozenset()),
        ("2025", frozenset({2025})),
        ("2024,2025", frozenset({2024, 2025})),
        ("2024.2025", frozenset({2024, 2025})),
        ("  2024 , 2025 ", frozenset({2024, 2025})),
        ("2020,2021,2022,2023,2024", frozenset({2020, 2021, 2022, 2023, 2024})),
        ("garbage,2024", frozenset({2024})),
    ],
)
def test_parse_year_set(raw: str, expected: frozenset[int]) -> None:
    assert parse_year_set(raw) == expected


def test_parse_year_set_handles_none() -> None:
    assert parse_year_set(None) == frozenset()


def test_parse_abis_csv_skips_invalid_isin(fixture_csv: Path) -> None:
    records = parse_abis_csv(fixture_csv)
    assert all(len(r.isin) == 12 for r in records)
    assert "BAD-ISIN" not in {r.isin for r in records}


def test_parse_abis_csv_strips_isin_whitespace(fixture_csv: Path) -> None:
    records = parse_abis_csv(fixture_csv)
    # Row 1 had a trailing-space ISIN.
    assert any(r.isin == "XX0000000001" for r in records)


def test_parse_abis_csv_handles_tom_placeholder(fixture_csv: Path) -> None:
    records = parse_abis_csv(fixture_csv)
    rec = next(r for r in records if r.isin == "XX0000000002")
    # ``[tom]`` slots should round-trip to None, not the literal string.
    assert rec.shareclass is None
    assert rec.lei is None
    assert rec.cvr is None
    assert rec.tin is None
    assert rec.subfund == "Synthetic Sub-fund B"


def test_parse_abis_csv_accepts_dot_separated_years(fixture_csv: Path) -> None:
    records = parse_abis_csv(fixture_csv)
    rec = next(r for r in records if r.isin == "XX0000000002")
    assert rec.registered_years == frozenset({2024, 2025})
    assert rec.unregistered_years == frozenset({2020, 2021})


def test_parse_abis_csv_keeps_share_classes_separate(fixture_csv: Path) -> None:
    """Two share-classes of the same ISIN remain separate at parse time."""
    records = parse_abis_csv(fixture_csv)
    rows = [r for r in records if r.isin == "XX0000000003"]
    assert len(rows) == 2
    assert {r.shareclass for r in rows} == {"Class A", "Class B"}


def test_records_to_observations_unions_share_classes(tmp_path: Path) -> None:
    records = _parse_fixture_text(tmp_path, ABIS_CSV_FIXTURE_TEXT)
    observations = _records_to_observations(list(records))
    obs_for_3 = [o for o in observations if o.isin == "XX0000000003"]
    listed_years = {o.tax_year for o in obs_for_3 if o.listed}
    unlisted_years = {o.tax_year for o in obs_for_3 if not o.listed}
    # Class A: listed=2025, unlisted=2020-2024
    # Class B: listed=2024,2025, unlisted=2020-2023
    # Union with listed-wins → listed: 2024,2025; unlisted: 2020-2023.
    assert listed_years == {2024, 2025}
    assert unlisted_years == {2020, 2021, 2022, 2023}


def test_records_to_observations_emits_only_unlisted_for_delisted_isins(
    tmp_path: Path,
) -> None:
    records = _parse_fixture_text(tmp_path, ABIS_CSV_FIXTURE_TEXT)
    observations = _records_to_observations(list(records))
    obs_for_4 = [o for o in observations if o.isin == "XX0000000004"]
    assert obs_for_4
    assert all(not o.listed for o in obs_for_4)
    assert {o.tax_year for o in obs_for_4} == {2024, 2025}


def test_parse_abis_csv_rejects_misaligned_header(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("Foo,Bar,Baz,Qux,Quux,Corge,Grault,Garply,Waldo,Fred\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ABIS CSV header"):
        parse_abis_csv(bad)


# --- helpers ---------------------------------------------------------------


def _parse_fixture_text(tmp_path: Path, text: str) -> tuple:  # type: ignore[type-arg]
    """Parse the fixture text via a tmp_path-backed CSV file.

    The file is created under pytest's ``tmp_path`` so it is cleaned
    up automatically at the end of the test.
    """
    path = tmp_path / "abis_fixture.csv"
    path.write_text(text, encoding="utf-8")
    return parse_abis_csv(path)
