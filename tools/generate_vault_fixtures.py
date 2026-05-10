"""Generate synthetic vault PDF fixtures.

Produces three small reportlab-rendered PDFs under
``tests/vault/fixtures/`` containing well-known DA / DE / EN text.
The fixtures are *deterministic* — re-running this script overwrites
the previous output bit-for-bit (modulo PDF metadata that reportlab
seeds from creation time, which we override below).

The vault tests rely on these fixtures having embedded text so the
OCR layer's "embedded text fast path" can be exercised without
requiring Tesseract during unit tests. A separate test that *does*
require Tesseract (``test_ocr_tesseract_path``) is gated on
``shutil.which("tesseract")``.

Usage::

    uv run --group parsers python tools/generate_vault_fixtures.py
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "tests" / "vault" / "fixtures"


SAMPLES = {
    "sample_dk.pdf": [
        "Aarsoversigt 2025 - Penge Test Bank",
        "Kontoejer: Test Bruger",
        "Saldo pr. 31. december: 12345,67 DKK",
        "Renteindtaegt: 234,56 DKK",
        "Skat indeholdt: 25,00 DKK",
    ],
    "sample_de.pdf": [
        "Jahressteuerbescheinigung 2025 - Penge Testbank",
        "Kontoinhaber: Test Nutzer",
        "Vorabpauschale: 123,45 EUR",
        "Teilfreistellung: 30 Prozent",
        "Kapitalertragsteuer: 56,78 EUR",
    ],
    "sample_en.pdf": [
        "Annual Statement 2025 - Penge Test Bank",
        "Account holder: Test User",
        "Closing balance: 9876.54 EUR",
        "Interest income: 123.45 EUR",
        "Tax withheld: 12.34 EUR",
    ],
}


def _render(path: Path, lines: list[str]) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    # Pin metadata so re-runs produce stable bytes for review-friendly diffs.
    c.setTitle(path.stem)
    c.setAuthor("penge-vault tests")
    c.setSubject("synthetic vault fixture")
    c.setCreator("tools/generate_vault_fixtures.py")
    width, height = A4
    del width
    y = height - 80
    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, y, lines[0])
    y -= 30
    c.setFont("Helvetica", 11)
    for line in lines[1:]:
        c.drawString(72, y, line)
        y -= 18
    c.showPage()
    c.save()


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for filename, lines in SAMPLES.items():
        _render(FIXTURE_DIR / filename, lines)
        print(f"wrote {FIXTURE_DIR / filename}")


if __name__ == "__main__":
    main()
