"""GoCardless Bank Account Data (PSD2) API client.

.. deprecated::
    GoCardless paused new Bank Account Data signups in early 2026. New
    Penge connectors target :mod:`penge.ingest.enablebanking` instead
    (issues #14 GLS, #15 EBank, #16 Lunar). This module is retained for
    grandfathered credentials and as a historical reference; expect
    no new development.

Transport-only client: token management, institution discovery,
requisition creation, and the read-only account endpoints
(transactions, balances, details, metadata).
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
