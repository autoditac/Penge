"""DK tax constants — 2026 baseline.

All amounts are in DKK unless otherwise stated.  Values are adjusted by SKAT
annually; update this file each year and commit a corresponding ADR note.

Sources (2026):
- SKAT — https://skat.dk/data/satser
- Ankestyrelsen — folkepension grundbeløb og tillæg (Jan 2026)
- Pensionsinfo / Finanstilsynet — folkepensionsalder schedule
"""

from __future__ import annotations

from decimal import Decimal

__all__ = [
    "DK_TOPSKAT_RATE",
    "DK_TOPSKAT_THRESHOLD_DKK",
    "FOLKEPENSION_AGE_SCHEDULE",
    "FOLKEPENSION_GRUNDBELOEB_MONTHLY_DKK",
    "FOLKEPENSION_INCOME_THRESHOLD_DKK",
    "FOLKEPENSION_MODREGNING_RATE",
    "FOLKEPENSION_TILLAEG_MARRIED_MONTHLY_DKK",
    "FOLKEPENSION_TILLAEG_SINGLE_MONTHLY_DKK",
]

# ---------------------------------------------------------------------------
# Topskat
# ---------------------------------------------------------------------------

#: Topskat rate (15 % on personal income above the threshold).
DK_TOPSKAT_RATE: Decimal = Decimal("0.15")

#: Annual personal-income threshold above which Topskat is levied (DKK, 2026).
#: Applies after personfradrag has been deducted.
DK_TOPSKAT_THRESHOLD_DKK: Decimal = Decimal("588900")

# ---------------------------------------------------------------------------
# Folkepension (2026 approximate monthly amounts)
# ---------------------------------------------------------------------------

#: Grundbeløb — universal, not means-tested (monthly, DKK, 2026).
FOLKEPENSION_GRUNDBELOEB_MONTHLY_DKK: Decimal = Decimal("7191")

#: Maximum pensionstillæg for a single pensioner (monthly, DKK, 2026).
FOLKEPENSION_TILLAEG_SINGLE_MONTHLY_DKK: Decimal = Decimal("18389")

#: Maximum pensionstillæg for a married/cohabiting pensioner (monthly, DKK, 2026).
FOLKEPENSION_TILLAEG_MARRIED_MONTHLY_DKK: Decimal = Decimal("8993")

#: Modregning rate: the tillæg is reduced by this fraction of annual private
#: pension income *exceeding* the income threshold (30.9 %, 2026).
FOLKEPENSION_MODREGNING_RATE: Decimal = Decimal("0.309")

#: Annual private-income threshold below which no modregning applies (DKK, 2026).
#: The same threshold applies to both single and married pensioners.
FOLKEPENSION_INCOME_THRESHOLD_DKK: Decimal = Decimal("94800")

# ---------------------------------------------------------------------------
# Folkepensionsalder schedule
# ---------------------------------------------------------------------------

#: Mapping from the *calendar year* in which a given folkepensionsalder takes
#: effect to the new age.  A pensioner born in 1963 turns 67 in 2030 — but the
#: schedule is indexed to *calendar year*, not birth year, per the law.
#:
#: Schedule per Lov om social pension (LBK nr 1116 af 26/09/2019) + amendments:
#:   - Up to 2029: folkepensionsalder = 67
#:   - 2030-2034:  folkepensionsalder = 68
#:   - From 2035:  folkepensionsalder = 69  (subject to future life-expectancy review)
FOLKEPENSION_AGE_SCHEDULE: dict[int, int] = {
    2026: 67,
    2030: 68,
    2035: 69,
}
