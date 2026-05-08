"""Evangelische Bank PSD2 connector (issue #15).

Evangelische Bank (German cooperative bank, BIC ``GENODEF1EK1``)
exposes account data through the PSD2 AISP API which Penge consumes
via Enable Banking. The transport client lives in
:mod:`penge.ingest.enablebanking`; this package is a thin per-bank
wrapper that fixes the provider slug and ASPSP name.
"""

from penge.ingest.enablebanking.mapping import (
    balance_to_market_value,
    transaction_to_row,
)

from .loader import LoadResult, load_account

__all__ = [
    "LoadResult",
    "balance_to_market_value",
    "load_account",
    "transaction_to_row",
]
