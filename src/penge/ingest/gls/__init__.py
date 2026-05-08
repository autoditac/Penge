"""GLS Bank PSD2 connector (issue #14).

GLS Bank (German cooperative bank, BIC ``GENODEM1GLS``) exposes
account data through the PSD2 AISP API which Penge consumes via
Enable Banking. The transport client lives in
:mod:`penge.ingest.enablebanking`; this package wires it into the
canonical ``transaction`` and ``holding_snapshot`` tables.
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
