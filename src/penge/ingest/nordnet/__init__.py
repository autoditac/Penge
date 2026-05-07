"""Nordnet (Denmark) CSV ingest connector.

Parses Nordnet's transaction and holdings CSV exports for the DK
locale into typed canonical records. See ADR-0008 for the data
modelling rules (account kinds, multi-currency cash, ASK tax).

This module is parse-only; loading parsed records into Postgres is
the responsibility of a follow-up loader (analogous to
`penge.ingest.ecb_fx.upsert`).
"""

from penge.ingest.nordnet.config import AccountConfig, AccountsConfig, load_accounts_config
from penge.ingest.nordnet.constants import (
    ACCOUNT_KIND_AKTIEDEPOT,
    ACCOUNT_KIND_AKTIESPAREKONTO,
    ACCOUNT_KIND_OPSPARINGSKONTO,
    ACCOUNT_KINDS,
    TXN_KIND_BUY,
    TXN_KIND_CASH_INTEREST,
    TXN_KIND_DEPOSIT,
    TXN_KIND_DIVIDEND,
    TXN_KIND_INTERNAL_TRANSFER,
    TXN_KIND_SELL,
    TXN_KIND_TAX_ASK_CHARGE,
    TXN_KIND_TAX_ASK_PAYMENT,
    TXN_KIND_WITHDRAWAL,
)
from penge.ingest.nordnet.models import (
    ParsedCashBalance,
    ParsedHolding,
    ParsedHoldingsFile,
    ParsedTransaction,
)
from penge.ingest.nordnet.parser import (
    UnknownAccountError,
    derive_cash_balances,
    instrument_map_from_transactions,
    parse_holdings,
    parse_holdings_file,
    parse_holdings_filename,
    parse_transactions,
)

__all__ = [
    "ACCOUNT_KIND_AKTIEDEPOT",
    "ACCOUNT_KIND_AKTIESPAREKONTO",
    "ACCOUNT_KIND_OPSPARINGSKONTO",
    "ACCOUNT_KINDS",
    "AccountConfig",
    "AccountsConfig",
    "ParsedCashBalance",
    "ParsedHolding",
    "ParsedHoldingsFile",
    "ParsedTransaction",
    "TXN_KIND_BUY",
    "TXN_KIND_CASH_INTEREST",
    "TXN_KIND_DEPOSIT",
    "TXN_KIND_DIVIDEND",
    "TXN_KIND_INTERNAL_TRANSFER",
    "TXN_KIND_SELL",
    "TXN_KIND_TAX_ASK_CHARGE",
    "TXN_KIND_TAX_ASK_PAYMENT",
    "TXN_KIND_WITHDRAWAL",
    "UnknownAccountError",
    "derive_cash_balances",
    "instrument_map_from_transactions",
    "load_accounts_config",
    "parse_holdings",
    "parse_holdings_file",
    "parse_holdings_filename",
    "parse_transactions",
]
