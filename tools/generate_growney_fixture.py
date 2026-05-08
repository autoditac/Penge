"""Generate the synthetic Sutor Depotauszug PDF used by tests.

Run with ``uv run --group parsers python tools/generate_growney_fixture.py``.
The script overwrites ``tests/ingest/growney/fixtures/sample_depotauszug.pdf``
in place. The generated file uses fictional account numbers, IBANs,
and ETF holdings shaped exactly like the real Sutor layout so the
parser can be exercised end-to-end without committing real data.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "ingest"
    / "growney"
    / "fixtures"
    / "sample_depotauszug.pdf"
)

DEPOT_NUMBER = "9999999999"
IBAN = "DE00 2023 0800 9999 9999 99"
STRATEGY = "growgreen100"
AS_OF = "31.03.2026"

HOLDINGS_HEADER = [
    "Investment",
    "ISIN",
    "Lagerstelle",
    "Verwahrart",
    "Anlagequote",
    "Bestand",
    "Einheit",
    "Kurs",
    "Währung",
    "Kurswert",
]

HOLDINGS_ROWS: list[list[str]] = [
    [
        "UBS ETF - MSCI EMU Socially Resp.",
        "LU0629460675",
        "Deutschland",
        "Girosammelverwahrung",
        "4,99 %",
        "0,6186",
        "Anteile",
        "125,5383",
        "EUR",
        "77,66 EUR",
    ],
    [
        "UBS MSCI Pacific Social Resp ETF",
        "LU0629460832",
        "Deutschland",
        "Girosammelverwahrung",
        "10,15 %",
        "2,1941",
        "Anteile",
        "85,6202",
        "US$*",
        "163,38 EUR",
    ],
    [
        "iShares MSCI Europe SRI ETF dis",
        "IE00BGDPWW94",
        "Irland",
        "Wertpapierrechnung",
        "16,60 %",
        "36,9062",
        "Anteile",
        "7,1233",
        "EUR",
        "262,89 EUR",
    ],
    [
        "iShares MSCI USA SRI UCITS ETF dis",
        "IE00BZ173T46",
        "Irland",
        "Wertpapierrechnung",
        "42,49 %",
        "70,1539",
        "Anteile",
        "11,5337",
        "US$*",
        "703,72 EUR",
    ],
    [
        "iShares MSCI EM SRI UCITS ETF dis",
        "IE00BGDQ0T50",
        "Irland",
        "Wertpapierrechnung",
        "25,77 %",
        "71,7871",
        "Anteile",
        "6,4344",
        "US$*",
        "401,73 EUR",
    ],
]

TXN_HEADER = [
    "Buchungs-\ndatum",
    "Wertstellung",
    "Transaktion\nHandelsplatz",
    "Umsatz / Finanz-Instrument\nISIN",
    "Anteile / Gramm\nKurs / Preis",
    "W-Kurs\nWährung",
    "Betrag\n(brutto)",
    "Betrag\n(netto)",
    "Kosten",
    "KESt\nSolZ",
    "KiSt",
]

TXN_ROWS: list[list[str]] = [
    [
        "02.01.2026",
        "02.01.2026",
        "Einzahlung",
        "automatischer Lastschrifteinzug",
        "-",
        "-",
        "",
        "50,00",
        "",
        "",
        "",
    ],
    [
        "05.01.2026",
        "02.01.2026\n11:16",
        "Kauf\nTradegate",
        "Kauf UBS ETF - MSCI EMU Socially Resp.\nLU0629460675",
        "0,0148\n136,0400",
        "EUR",
        "",
        "-2,02",
        "",
        "",
        "",
    ],
    [
        "05.01.2026",
        "02.01.2026\n12:51",
        "Kauf\nTradegate",
        "Kauf iShares MSCI USA SRI UCITS ETF dis\nIE00BZ173T46",
        "2,4378\n11,9671",
        "1,1721\nUS$",
        "",
        "-24,89",
        "",
        "",
        "",
    ],
    [
        "07.01.2026",
        "29.12.2025",
        "Ausschüttung",
        "Betrag der Ausschüttung iShares MSCI USA SRI UCITS ETF\nIE00BZ173T46",
        "-",
        "US$",
        "",
        "2,98",
        "",
        "",
        "",
    ],
    [
        "02.02.2026",
        "02.02.2026",
        "Gebühr",
        "Servicegebühr 01.10.2025 - 31.12.2025",
        "-",
        "-",
        "",
        "-1,24",
        "",
        "",
        "",
    ],
]


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
        title="Sutor Depotauszug (synthetic test fixture)",
    )
    styles = getSampleStyleSheet()
    bold = ParagraphStyle(
        "bold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        spaceAfter=6,
    )
    normal = styles["Normal"]
    flow = []
    flow.append(Paragraph("Depotauszug (Synthetic Test Fixture)", styles["Heading1"]))
    flow.append(
        Paragraph(
            "Diese Datei wurde automatisch erzeugt und enthält keine echten Daten.",
            normal,
        )
    )
    flow.append(Paragraph(f"Sutor Bank — Depotnummer: {DEPOT_NUMBER}", normal))
    flow.append(Paragraph(f"IBAN: {IBAN}", normal))
    flow.append(PageBreak())

    flow.append(
        Paragraph(
            f"Aufstellung über Kundenfinanzinstrumente per {AS_OF}",
            styles["Heading2"],
        )
    )
    flow.append(Paragraph("Test User", normal))
    flow.append(
        Paragraph(
            f'"{STRATEGY}" Nr. {DEPOT_NUMBER} / IBAN: {IBAN}',
            bold,
        )
    )
    flow.append(Spacer(1, 6))
    holdings_table = Table(
        [HOLDINGS_HEADER, *HOLDINGS_ROWS],
        repeatRows=1,
    )
    holdings_table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 7),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ]
        )
    )
    flow.append(holdings_table)
    flow.append(Spacer(1, 6))
    flow.append(Paragraph("* Währungskurs: 1,1498 US$", normal))
    flow.append(Paragraph("Kurswert Gesamt 1.609,38 EUR", bold))
    flow.append(Paragraph("Geldsaldo 0,00 EUR", normal))
    flow.append(PageBreak())

    flow.append(
        Paragraph(
            "Umsätze vom 01.01.2026 bis 31.03.2026 in EUR",
            styles["Heading2"],
        )
    )
    flow.append(Spacer(1, 6))
    txn_table = Table(
        [TXN_HEADER, *TXN_ROWS],
        repeatRows=1,
    )
    txn_table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 7),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    flow.append(txn_table)

    doc.build(flow)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
