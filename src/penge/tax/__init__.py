"""Penge tax module.

Subpackages and modules:

- :mod:`penge.tax.abis` — Skat ABIS list ingestor (issue #34).
- :mod:`penge.tax.lots` — tax-lot tracker (gennemsnitsmetoden, issue #35,
  ADR-0016).
- :mod:`penge.tax.lager` — lagerbeskatning calculator (issue #36, ADR-0017).
- :mod:`penge.tax.aktiesparekonto` — ASK 17 % wrapper (issue #37, ADR-0018).
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

__all__ = [
    "ASK_DEPOSIT_CAPS",
    "ASK_RATE",
    "AskDeposit",
    "AskError",
    "AskTaxResult",
    "Buy",
    "BuyLeg",
    "Distribution",
    "LagerError",
    "LagerInput",
    "LagerResult",
    "LotBook",
    "LotError",
    "Merge",
    "Money",
    "RealisedGain",
    "Sell",
    "SellLeg",
    "Split",
    "TaxLot",
    "check_deposit_cap",
    "compute_ask_tax",
    "compute_ask_taxes",
    "compute_lager",
    "compute_lager_many",
    "sum_gain_by_year",
]
