"""Lunar PSD2 connector (issue #16).

Lunar (Danish challenger bank, BIC ``LNHBDKKB``) exposes account data
through PSD2 AISP. Penge consumes it via Enable Banking; the
transport client lives in :mod:`penge.ingest.enablebanking` and this
package is a thin per-bank wrapper that fixes the provider slug,
ASPSP name, and Aktiesparekonto auto-tagging.

The Aktiesparekonto (ASK) is a Danish tax-advantaged stock savings
account with a 17 % flat lagerbeskatning (mark-to-market) tax rate
and an annual contribution cap. Lunar exposes ASK as a separate
subaccount whose product field contains ``"Aktiesparekonto"``. The
connector tags such accounts with ``dk_tax_treatment="aktiesparekonto"``
so downstream tax models can apply the correct regime.
"""

from penge.ingest.enablebanking.mapping import (
    balance_to_market_value,
    transaction_to_row,
)

from .loader import LoadResult, is_aktiesparekonto, load_account

__all__ = [
    "LoadResult",
    "balance_to_market_value",
    "is_aktiesparekonto",
    "load_account",
    "transaction_to_row",
]
