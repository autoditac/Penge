"""Nordnet (Denmark) CSV ingest connector.

Parses Nordnet's transaction and holdings CSV exports for the DK
locale into typed canonical records and upserts them into the
operational Postgres schema. See ADR-0008 for the data modelling
rules (account kinds, multi-currency cash, ASK tax).

The package exposes both a parse-only API (``parse_transactions``,
``parse_holdings_file``, ``derive_cash_balances``) and a loader
(``load_files``, ``load_records``) backed by the ``penge-nordnet``
CLI entrypoint.
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
from penge.ingest.nordnet.loader import (
    CASH_INSTRUMENT_KIND,
    CASH_TICKER_PREFIX,
    PROVIDER,
    LoadResult,
    load_files,
    load_records,
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
    "ACCOUNT_KINDS",
    "ACCOUNT_KIND_AKTIEDEPOT",
    "ACCOUNT_KIND_AKTIESPAREKONTO",
    "ACCOUNT_KIND_OPSPARINGSKONTO",
    "CASH_INSTRUMENT_KIND",
    "CASH_TICKER_PREFIX",
    "PROVIDER",
    "TXN_KIND_BUY",
    "TXN_KIND_CASH_INTEREST",
    "TXN_KIND_DEPOSIT",
    "TXN_KIND_DIVIDEND",
    "TXN_KIND_INTERNAL_TRANSFER",
    "TXN_KIND_SELL",
    "TXN_KIND_TAX_ASK_CHARGE",
    "TXN_KIND_TAX_ASK_PAYMENT",
    "TXN_KIND_WITHDRAWAL",
    "AccountConfig",
    "AccountsConfig",
    "LoadResult",
    "ParsedCashBalance",
    "ParsedHolding",
    "ParsedHoldingsFile",
    "ParsedTransaction",
    "UnknownAccountError",
    "derive_cash_balances",
    "instrument_map_from_transactions",
    "load_accounts_config",
    "load_files",
    "load_records",
    "parse_holdings",
    "parse_holdings_file",
    "parse_holdings_filename",
    "parse_transactions",
]
