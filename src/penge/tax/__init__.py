"""Penge tax module.

Subpackages and modules:

- :mod:`penge.tax.abis` — Skat ABIS list ingestor (issue #34).
- :mod:`penge.tax.lots` — tax-lot tracker (gennemsnitsmetoden, issue #35,
  ADR-0016).
- :mod:`penge.tax.lager` — lagerbeskatning calculator (issue #36, ADR-0017).
- :mod:`penge.tax.aktiesparekonto` — ASK 17 % wrapper (issue #37, ADR-0018).
- :mod:`penge.tax.pal` — PAL-skat 15.3 % pension yield tax (issue #38,
  ADR-0019).
- :mod:`penge.tax.report_dk` — SKAT-format report generator (issue #39,
  ADR-0020).
- :mod:`penge.tax.de_vorab` — DE Vorabpauschale + Teilfreistellung
  (issue #40, ADR-0021).
"""

from penge.tax.aktiesparekonto import (
    ASK_DEPOSIT_CAPS,
    ASK_RATE,
    AskDeposit,
    AskError,
    AskTaxResult,
    check_deposit_cap,
    compute_ask_tax,
    compute_ask_taxes,
)
from penge.tax.de_vorab import (
    ABGELT_RATE,
    BASISZINS_DE,
    TEILFREISTELLUNG_QUOTES,
    FundClassification,
    VorabError,
    VorabInput,
    VorabResult,
    compute_vorabpauschale,
    compute_vorabpauschale_many,
)
from penge.tax.de_vorab import to_markdown as to_markdown_vorab
from penge.tax.lager import (
    BuyLeg,
    Distribution,
    LagerError,
    LagerInput,
    LagerResult,
    SellLeg,
    compute_lager,
    compute_lager_many,
    sum_gain_by_year,
)
from penge.tax.lots import (
    Buy,
    LotBook,
    LotError,
    Merge,
    Money,
    RealisedGain,
    Sell,
    Split,
    TaxLot,
)
from penge.tax.pal import (
    PAL_RATE,
    PalContribution,
    PalError,
    PalInput,
    PalResult,
    PalWithdrawal,
    compute_pal,
    compute_pal_many,
)
from penge.tax.report_dk import (
    SkatReport,
    SkatReportError,
    SkatReportRow,
    build_skat_report,
    to_csv,
    to_markdown,
)

__all__ = [
    "ABGELT_RATE",
    "ASK_DEPOSIT_CAPS",
    "ASK_RATE",
    "AskDeposit",
    "AskError",
    "AskTaxResult",
    "BASISZINS_DE",
    "Buy",
    "BuyLeg",
    "Distribution",
    "FundClassification",
    "LagerError",
    "LagerInput",
    "LagerResult",
    "LotBook",
    "LotError",
    "Merge",
    "Money",
    "PAL_RATE",
    "PalContribution",
    "PalError",
    "PalInput",
    "PalResult",
    "PalWithdrawal",
    "RealisedGain",
    "Sell",
    "SellLeg",
    "SkatReport",
    "SkatReportError",
    "SkatReportRow",
    "Split",
    "TEILFREISTELLUNG_QUOTES",
    "TaxLot",
    "VorabError",
    "VorabInput",
    "VorabResult",
    "build_skat_report",
    "check_deposit_cap",
    "compute_ask_tax",
    "compute_ask_taxes",
    "compute_lager",
    "compute_lager_many",
    "compute_pal",
    "compute_pal_many",
    "compute_vorabpauschale",
    "compute_vorabpauschale_many",
    "sum_gain_by_year",
    "to_csv",
    "to_markdown",
    "to_markdown_vorab",
]
