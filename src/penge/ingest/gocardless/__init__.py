"""GoCardless Bank Account Data (PSD2) API client.

This is a *base* client only — it covers token management, institution
discovery, requisition creation, and the read-only account endpoints
(transactions, balances, details, metadata). Higher-level normalisation
into the Penge transaction model lives elsewhere.

See ``docs/connectors/gocardless.md`` for the human consent runbook.
"""

from penge.ingest.gocardless.client import Client, ClientError, TokenCache
from penge.ingest.gocardless.models import (
    AccountBalances,
    AccountDetails,
    Balance,
    Institution,
    Requisition,
    Token,
    Transaction,
    TransactionsPage,
)

__all__ = [
    "AccountBalances",
    "AccountDetails",
    "Balance",
    "Client",
    "ClientError",
    "Institution",
    "Requisition",
    "Token",
    "TokenCache",
    "Transaction",
    "TransactionsPage",
]
