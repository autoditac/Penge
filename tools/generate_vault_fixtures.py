"""Generate synthetic vault PDF fixtures.

Produces three small reportlab-rendered PDFs under
``tests/vault/fixtures/`` containing well-known DA / DE / EN text.

We enable reportlab's ``invariant`` mode and override creation-time
metadata so re-runs produce reproducibly identical bytes for
review-friendly diffs. Older reportlab releases that do not honour
``invariant`` may still produce small byte-level deltas around the PDF
trailer; that is acceptable because the vault tests assert on
*content*, not on byte equality.

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

from reportlab import rl_config
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

rl_config.invariant = 1

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

# Labeled fixtures for the rule-based classifier confusion matrix
# (issue #42). Filename prefix is the expected category; the body
# contains category-distinctive tokens in DA / DE / EN. ASCII-only
# filenames keep the tree portable across filesystems even though the
# category labels themselves are unicode.
LABELED_SAMPLES: dict[str, tuple[str, list[str]]] = {
    "lonseddel_01.pdf": (
        "lønseddel",
        [
            "Lønseddel marts 2025 - Penge Test ApS",
            "Lønperiode: 01.03.2025 - 31.03.2025",
            "Bruttoløn: 45000,00 DKK",
            "Attrukket A-skat: 12345,00 DKK",
            "Arbejdsmarkedsbidrag: 3600,00 DKK",
            "Feriepenge: 5400,00 DKK",
        ],
    ),
    "lonseddel_02.pdf": (
        "lønseddel",
        [
            "Lønspecifikation - april 2025",
            "Medarbejder: Test Bruger",
            "Lønperiode 01.04.2025 - 30.04.2025",
            "Arbejdsmarkedsbidrag: 3700,00 DKK",
            "Feriepenge optjent: 5550,00 DKK",
        ],
    ),
    "gehaltsabrechnung_01.pdf": (
        "gehaltsabrechnung",
        [
            "Gehaltsabrechnung März 2025 - Penge Test GmbH",
            "Mitarbeiter: Test Nutzer",
            "Bruttogehalt: 5000,00 EUR",
            "Lohnsteuer: 800,00 EUR",
            "Sozialversicherungsbeitrag: 1000,00 EUR",
            "Auszahlungsbetrag: 3200,00 EUR",
        ],
    ),
    "gehaltsabrechnung_02.pdf": (
        "gehaltsabrechnung",
        [
            "Entgeltabrechnung April 2025",
            "Verdienstabrechnung für Test Nutzer",
            "Lohnsteuer: 820,00 EUR",
            "Sozialversicherungsbeitrag: 1010,00 EUR",
        ],
    ),
    "aarsopgorelse_01.pdf": (
        "årsopgørelse",
        [
            "Årsopgørelse 2024 - Skattestyrelsen",
            "CPR: XXXXXX-XXXX",
            "Skattepligtig indkomst: 540000 DKK",
            "Restskat: 1234 DKK",
            "Overskydende skat: 0 DKK",
        ],
    ),
    "aarsopgorelse_02.pdf": (
        "årsopgørelse",
        [
            "Forskudsopgørelse 2025 - Skattestyrelsen",
            "Skattepligtig indkomst forventet: 560000 DKK",
            "Restskat forventet: 0 DKK",
        ],
    ),
    "steuerbescheid_01.pdf": (
        "steuerbescheid",
        [
            "Einkommensteuerbescheid für 2024 - Finanzamt Berlin",
            "Festsetzung der Einkommensteuer",
            "Zu versteuerndes Einkommen: 60000 EUR",
            "Solidaritätszuschlag: 0 EUR",
            "Steuerbescheid Datum: 15.05.2025",
        ],
    ),
    "steuerbescheid_02.pdf": (
        "steuerbescheid",
        [
            "Steuerbescheid 2023 - Finanzamt München",
            "Festsetzung der Einkommensteuer 2023",
            "Zu versteuerndes Einkommen: 58000 EUR",
        ],
    ),
    "kontoauszug_01.pdf": (
        "kontoauszug",
        [
            "Kontoauszug Nr. 03/2025 - GLS Bank",
            "IBAN: DE00 0000 0000 0000 0000 00",
            "Buchungstag: 15.03.2025",
            "Valutadato: 15.03.2025",
            "Kontostand: 1234,56 EUR",
        ],
    ),
    "kontoauszug_02.pdf": (
        "kontoauszug",
        [
            "Kontoudtog marts 2025 - Lunar Bank",
            "IBAN: DK00 0000 0000 0000 00",
            "Valutadato: 20.03.2025",
            "Saldo: 12345,67 DKK",
        ],
    ),
    "depotauszug_01.pdf": (
        "depotauszug",
        [
            "Depotauszug Q1 2025 - Penge Testbroker",
            "Depotaufstellung zum 31.03.2025",
            "Wertpapierabrechnung Nr. 12345",
            "Beholdningsoversigt pr. 31.03.2025",
        ],
    ),
    "depotauszug_02.pdf": (
        "depotauszug",
        [
            "Portfolio statement - Nordnet",
            "Beholdningsoversigt pr. 30.04.2025",
            "Værdipapirer: 10 positioner",
        ],
    ),
    "pfa_statement_01.pdf": (
        "pfa-statement",
        [
            "PFA Pension - Pensionsoversigt 2024",
            "Kunde: Test Bruger",
            "PFA Plus livrente: 1234567 DKK",
            "Ratepension: 234567 DKK",
            "Depotrente: 4,2 procent",
        ],
    ),
    "pfa_statement_02.pdf": (
        "pfa-statement",
        [
            "Pensionsoversigt 2025 - PFA Pension",
            "Livrente saldo: 1300000 DKK",
            "Ratepension saldo: 240000 DKK",
        ],
    ),
    "hypothek_01.pdf": (
        "hypothek",
        [
            "Hypothekendarlehen Jahresübersicht 2024",
            "Grundschuld eingetragen: 250000 EUR",
            "Tilgungsplan 2025-2055",
            "Zinsbindung bis 2034",
            "Zinssatz: 3,1 Prozent",
        ],
    ),
    "hypothek_02.pdf": (
        "hypothek",
        [
            "Realkreditlån - Penge Test Realkredit",
            "Realkredit hovedstol: 2500000 DKK",
            "Tilgungsplan vedlagt",
            "Zinssatz: 4,0 procent",
        ],
    ),
    "grundbuch_01.pdf": (
        "grundbuch",
        [
            "Grundbuchauszug - Amtsgericht Berlin",
            "Bestandsverzeichnis: Flurstück 42",
            "Abteilung II: Lasten",
            "Eigentümer: Test Nutzer",
        ],
    ),
    "grundbuch_02.pdf": (
        "grundbuch",
        [
            "Grundbuchblatt 1234 - Grundbuchamt Hamburg",
            "Bestandsverzeichnis: Flurstück 99",
            "Eigentümer: Test Nutzer",
        ],
    ),
    "versicherungspolice_01.pdf": (
        "versicherungspolice",
        [
            "Versicherungspolice - Penge Test Versicherung",
            "Versicherungsschein Nr. 99887766",
            "Policenummer: 99887766",
            "Prämie jährlich: 240,00 EUR",
        ],
    ),
    "versicherungspolice_02.pdf": (
        "versicherungspolice",
        [
            "Forsikringspolice - Penge Test Forsikring",
            "Policenr.: 12345678",
            "Præmie årligt: 1800 DKK",
        ],
    ),
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
    labeled_dir = FIXTURE_DIR / "labeled"
    labeled_dir.mkdir(parents=True, exist_ok=True)
    for filename, (_label, lines) in LABELED_SAMPLES.items():
        _render(labeled_dir / filename, lines)
        print(f"wrote {labeled_dir / filename}")


if __name__ == "__main__":
    main()
