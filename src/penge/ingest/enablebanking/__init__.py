"""Enable Banking Open Banking API client (transport-only).

Powers PSD2 connectors for issues #14 (GLS), #15 (EBank), and #16
(Lunar). The API is a Berlin Group-flavoured aggregator: JWT auth
(RS256, signed with an RSA private key), redirect consent flow, then
short-lived account UIDs scoped to a session.

Reference: https://enablebanking.com/docs/api/reference/
"""

from .client import Client, ClientConfig
from .models import (
    AccountResource,
    Aspsp,
    AuthorizeSessionResponse,
    Balance,
    BalancesResponse,
    StartAuthorizationResponse,
    Transaction,
    TransactionsResponse,
)

__all__ = [
    "AccountResource",
    "Aspsp",
    "AuthorizeSessionResponse",
    "Balance",
    "BalancesResponse",
    "Client",
    "ClientConfig",
    "StartAuthorizationResponse",
    "Transaction",
    "TransactionsResponse",
]
