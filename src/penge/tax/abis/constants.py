"""Constants for the ABIS list connector.

Vocabularies (mirrored in Alembic 0003 and ADR-0009):

- ``DK_TAX_LAGERBESKATNING`` / ``DK_TAX_REALISATION`` —
  values for ``instrument.dk_tax_treatment``.
- ``SOURCE_ABIS`` / ``SOURCE_MANUAL`` —
  values for ``instrument.dk_tax_treatment_source``.

CSV-shape constants:

- ``ABIS_PLACEHOLDER`` — Skat writes ``[tom]`` (Danish for "empty")
  into cells that have no value.
- ``EXPECTED_HEADERS`` — the canonical column header sequence.
"""

from __future__ import annotations

from typing import Final

DK_TAX_LAGERBESKATNING: Final = "lagerbeskatning"
DK_TAX_REALISATION: Final = "realisation"
TREATMENT_VALUES: Final = (DK_TAX_LAGERBESKATNING, DK_TAX_REALISATION)

SOURCE_ABIS: Final = "abis"
SOURCE_MANUAL: Final = "manual"
SOURCE_VALUES: Final = (SOURCE_ABIS, SOURCE_MANUAL)

ABIS_PLACEHOLDER: Final = "[tom]"

# The Skat CSV ships with a leading BOM and Danish/English bilingual
# headers. We strip the BOM and match on the Danish field name.
EXPECTED_HEADERS: Final = (
    "Registreringsland /Skattemæssigt hjemsted",
    "ISIN-kode",
    "Navn andelsklasse/Name Shareclass",
    "LEI kode",
    "CVR/SE/TIN",
    "Navn afdeling/Name Sub-fund",
    "TIN",
    "Navn/Name",
    "Registrerede år",
    "Ikke registrerede år",
)

# Column indexes for the headers above.
COL_COUNTRY: Final = 0
COL_ISIN: Final = 1
COL_SHARECLASS: Final = 2
COL_LEI: Final = 3
COL_CVR: Final = 4
COL_SUBFUND: Final = 5
COL_TIN: Final = 6
COL_NAME: Final = 7
COL_REG_YEARS: Final = 8
COL_UNREG_YEARS: Final = 9

# An ISIN is exactly 12 chars: 2 letter country code + 9 alphanumerics
# + 1 check digit. We do not validate the check digit (Skat occasionally
# emits ISINs with whitespace which we strip).
ISIN_LENGTH: Final = 12
