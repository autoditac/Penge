"""Tests for :mod:`penge.vault.classifier` (issue #42).

Two tiers:

* Fast text-only assertions on the rule format / threshold logic.
* A confusion matrix over the synthetic labeled PDFs under
  ``tests/vault/fixtures/labeled/``. The fixtures are reportlab-
  rendered with embedded text so OCR runs through pdfplumber and
  does not require Tesseract on the host. The confusion matrix is
  printed on failure for diagnosis.

The labeled fixture filenames encode the expected category as the
prefix before ``_NN.pdf``; ASCII slugs (``lonseddel``, ``aarsopgorelse``)
map back to the unicode category names via :data:`_LABEL_FROM_SLUG`.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest

from penge.vault.classifier import (
    UNSORTED_CATEGORY,
    Classification,
    classify,
    load_config,
)
from penge.vault.ocr import OCRConfig, extract_text

FIXTURES = Path(__file__).parent / "fixtures"
LABELED_DIR = FIXTURES / "labeled"

#: Map ASCII filename prefixes to the (possibly unicode) category
#: labels exposed in ``vault-classifier.yaml``.
_LABEL_FROM_SLUG: dict[str, str] = {
    "lonseddel": "lønseddel",
    "gehaltsabrechnung": "gehaltsabrechnung",
    "aarsopgorelse": "årsopgørelse",
    "steuerbescheid": "steuerbescheid",
    "kontoauszug": "kontoauszug",
    "depotauszug": "depotauszug",
    "pfa_statement": "pfa-statement",
    "hypothek": "hypothek",
    "grundbuch": "grundbuch",
    "versicherungspolice": "versicherungspolice",
}

#: Per-class precision bar from the issue's DoD.
PRECISION_BAR = 0.80


def _label_from_filename(path: Path) -> str:
    stem = path.stem
    # Strip the trailing ``_NN`` index, e.g. "kontoauszug_01" -> "kontoauszug".
    base = stem.rsplit("_", 1)[0]
    if base not in _LABEL_FROM_SLUG:
        raise AssertionError(f"unrecognised fixture stem {stem!r}; update _LABEL_FROM_SLUG")
    return _LABEL_FROM_SLUG[base]


def test_load_config_compiles_all_rules() -> None:
    cfg = load_config()
    assert cfg.rules, "config has no rules"
    names = {r.name for r in cfg.rules}
    expected = set(_LABEL_FROM_SLUG.values())
    missing = expected - names
    assert not missing, f"missing categories in YAML: {missing}"
    assert 0.0 < cfg.min_confidence <= 1.0


def test_classify_returns_unsorted_for_empty_text() -> None:
    result = classify("")
    assert result.category == UNSORTED_CATEGORY
    assert result.confidence == 0.0
    assert result.matched_rules == ()


def test_classify_returns_unsorted_for_unrelated_text() -> None:
    result = classify("Dies ist ein generischer Begleittext ohne Schlüsselwörter.")
    assert result.category == UNSORTED_CATEGORY


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Lønseddel marts 2025\nArbejdsmarkedsbidrag: 100 DKK\nFeriepenge: 200 DKK", "lønseddel"),
        ("Gehaltsabrechnung März 2025\nLohnsteuer: 100 EUR", "gehaltsabrechnung"),
        ("Årsopgørelse 2024 - Skattestyrelsen\nRestskat: 0 DKK", "årsopgørelse"),
        ("Steuerbescheid 2024\nFinanzamt Berlin\nSolidaritätszuschlag: 0", "steuerbescheid"),
        ("Kontoauszug Nr. 03/2025\nIBAN: DE00\nBuchungstag: 15.03.2025", "kontoauszug"),
        ("Depotauszug Q1 2025\nWertpapierabrechnung Nr. 1\nDepotaufstellung", "depotauszug"),
        ("PFA Pension Pensionsoversigt 2024\nLivrente: 1 DKK", "pfa-statement"),
        ("Hypothekendarlehen\nGrundschuld: 100 EUR\nTilgungsplan", "hypothek"),
        ("Grundbuchauszug\nBestandsverzeichnis: Flurstück 1\nEigentümer: X", "grundbuch"),
        (
            "Versicherungspolice Penge\nVersicherungsschein Nr. 1\nPolicenummer: 1",
            "versicherungspolice",
        ),
    ],
)
def test_classify_recognises_each_category(text: str, expected: str) -> None:
    result = classify(text)
    assert result.category == expected, f"got {result}"
    assert result.confidence >= load_config().min_confidence


def _format_confusion_matrix(matrix: dict[str, dict[str, int]], labels: list[str]) -> str:
    width = max(len(c) for c in [*labels, UNSORTED_CATEGORY]) + 2
    header = "actual \\ predicted".ljust(width) + "".join(
        c.ljust(width) for c in [*labels, UNSORTED_CATEGORY]
    )
    rows = [header]
    for actual in labels:
        cells = "".join(
            str(matrix[actual].get(predicted, 0)).ljust(width)
            for predicted in [*labels, UNSORTED_CATEGORY]
        )
        rows.append(actual.ljust(width) + cells)
    return "\n".join(rows)


def test_confusion_matrix_meets_precision_bar() -> None:
    """Run the classifier across every labeled fixture PDF.

    Asserts per-class precision ≥ :data:`PRECISION_BAR`. Prints the
    full confusion matrix on failure to make tuning the YAML rules
    actionable.
    """

    fixtures = sorted(LABELED_DIR.glob("*.pdf"))
    assert fixtures, (
        f"no labeled fixtures under {LABELED_DIR}; run tools/generate_vault_fixtures.py"
    )

    labels = sorted(set(_LABEL_FROM_SLUG.values()))
    matrix: dict[str, dict[str, int]] = {label: defaultdict(int) for label in labels}
    predictions: list[tuple[Path, str, Classification]] = []

    ocr_config = OCRConfig(langs="eng", dpi=150)
    for path in fixtures:
        actual = _label_from_filename(path)
        ocr = extract_text(path, ocr_config)
        result = classify(ocr.text)
        matrix[actual][result.category] += 1
        predictions.append((path, actual, result))

    # Per-class precision = TP / (TP + FP); a class with zero predictions
    # has undefined precision and is skipped (the recall bar from the
    # confusion matrix's rows still catches "always wrong" classes).
    failures: list[str] = []
    for predicted in labels:
        tp = matrix[predicted].get(predicted, 0)
        fp = sum(matrix[actual].get(predicted, 0) for actual in labels if actual != predicted)
        denom = tp + fp
        if denom == 0:
            continue
        precision = tp / denom
        if precision < PRECISION_BAR:
            failures.append(
                f"  {predicted}: precision {precision:.2f} < {PRECISION_BAR:.2f} (tp={tp}, fp={fp})"
            )

    # Also sanity-check recall: every fixture must be classified, not
    # left in unsorted, since the patterns are tuned for these inputs.
    unsorted_hits = sum(matrix[a].get(UNSORTED_CATEGORY, 0) for a in labels)
    if unsorted_hits:
        failures.append(f"  {unsorted_hits} fixture(s) fell back to unsorted")

    if failures:
        diag = ["confusion matrix:", _format_confusion_matrix(matrix, labels), "", "failures:"]
        diag.extend(failures)
        diag.append("")
        diag.append("predictions:")
        for path, actual, result in predictions:
            diag.append(
                f"  {path.name}: actual={actual} predicted={result.category} "
                f"confidence={result.confidence:.2f}"
            )
        pytest.fail("\n".join(diag))
