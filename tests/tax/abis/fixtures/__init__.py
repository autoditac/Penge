"""Anonymized synthetic ABIS-list fixture.

Hand-written to exercise every parser quirk we observed in the real
2020-2025 Skat CSV without leaking any real Skat identifiers:

- ``[tom]`` placeholders in optional columns.
- ISIN with trailing whitespace.
- ``,``-separated year list (quoted).
- ``.``-separated year list (Skat occasionally emits this form).
- An ISIN that appears twice (two share-classes) and must be merged.
- An invalid ISIN row (deliberately malformed; should be skipped).

The ISINs are deliberately fictional: ``XX0000000001`` … ``XX0000000004``.
``XX`` is not a valid ISO-3166 country code, so collisions with real
ISINs are not possible.
"""

from __future__ import annotations

# A literal CSV string (rather than a generator) so test expectations
# are obvious to a future reader. Encoded to bytes with UTF-8 BOM so
# the parser's ``utf-8-sig`` open() is exercised.
ABIS_CSV_FIXTURE_TEXT = (
    "Registreringsland /Skattem\u00e6ssigt hjemsted,ISIN-kode,"
    "Navn andelsklasse/Name Shareclass,LEI kode,CVR/SE/TIN,"
    "Navn afdeling/Name Sub-fund,TIN,Navn/Name,"
    "Registrerede \u00e5r,Ikke registrerede \u00e5r\n"
    # 1. trailing whitespace on the ISIN; year lists comma-separated;
    # all metadata populated.
    "Germany (DE),XX0000000001 ,Synthetic Equity Fund A,"
    "00000000000000000001,12-34-56,Synthetic Sub-fund A,"
    "TIN-1,Synthetic Equity Fund A,2025,"
    '"2020,2021,2022,2023,2024"\n'
    # 2. ``[tom]`` placeholders in several optional columns; year list
    # uses ``.`` separator.
    "Luxembourg (LU),XX0000000002,[tom],[tom],[tom],"
    "Synthetic Sub-fund B,[tom],Synthetic Equity Fund B,"
    '"2024.2025","2020.2021"\n'
    # 3. share-class A of XX0000000003 — listed in 2025.
    "Ireland (IE),XX0000000003,Class A,"
    "00000000000000000003,[tom],Synthetic Multi-Class Fund,"
    "[tom],Synthetic Multi-Class Fund Class A,2025,"
    '"2020,2021,2022,2023,2024"\n'
    # 4. share-class B of the same ISIN — class is listed for 2024 too;
    # union of years should win in the loader.
    "Ireland (IE),XX0000000003,Class B,"
    "00000000000000000003,[tom],Synthetic Multi-Class Fund,"
    "[tom],Synthetic Multi-Class Fund Class B,"
    '"2024,2025","2020,2021,2022,2023"\n'
    # 5. malformed ISIN — must be skipped by the parser with a warning.
    "Denmark (DK),BAD-ISIN,Bad Row,[tom],[tom],"
    "[tom],[tom],Should Not Appear,2025,[tom]\n"
    # 6. delisted-only row: never on the list. Should produce two
    # ListingObservations with listed=false and zero with listed=true.
    "Finland (FI),XX0000000004,Synthetic Delisted Fund,"
    "00000000000000000004,[tom],Synthetic Delisted Fund,"
    '[tom],Synthetic Delisted Fund,[tom],"2024,2025"\n'
)
