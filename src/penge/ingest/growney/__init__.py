"""Growney ingest connector (Sutor Bank Depotauszug PDF).

Growney is a German robo-advisor whose accounts are held at
Sutor Bank as the regulated custodian. Sutor mails a quarterly
**Depotauszug** PDF with the holdings table and a transactions
table (Umsätze) that together drive this connector. Growney's
own quarterly performance report is treated as a complementary
document — only the strategy name is read from it (optional).

Public API mirrors the Nordnet connector:

- pure parser surface (``parse_depotauszug``, ``parse_pdf``);
- loader entrypoints (``load_files``, ``load_records``);
- ``penge-growney`` CLI.

See `docs/connectors/growney.md` and the issue body for the
column-level layout. Issue #19 originally said "CSV parser";
Sutor exports PDFs only, so the connector parses PDFs.
"""

from penge.ingest.growney.constants import (
    ACCOUNT_KIND_AKTIEDEPOT,
    PROVIDER,
    TXN_KIND_BUY,
    TXN_KIND_DEPOSIT,
    TXN_KIND_DIVIDEND,
    TXN_KIND_FEE,
    TXN_KIND_SELL,
    TXN_KIND_WITHDRAWAL,
)
from penge.ingest.growney.loader import LoadResult, load_files, load_records
from penge.ingest.growney.models import (
    ParsedDepotauszug,
    ParsedHolding,
    ParsedTransaction,
)
from penge.ingest.growney.parser import (
    parse_depotauszug,
    parse_holdings_rows,
    parse_pdf,
    parse_transactions_rows,
    synthesize_external_id,
)

__all__ = [
    "ACCOUNT_KIND_AKTIEDEPOT",
    "PROVIDER",
    "TXN_KIND_BUY",
    "TXN_KIND_DEPOSIT",
    "TXN_KIND_DIVIDEND",
    "TXN_KIND_FEE",
    "TXN_KIND_SELL",
    "TXN_KIND_WITHDRAWAL",
    "LoadResult",
    "ParsedDepotauszug",
    "ParsedHolding",
    "ParsedTransaction",
    "load_files",
    "load_records",
    "parse_depotauszug",
    "parse_holdings_rows",
    "parse_pdf",
    "parse_transactions_rows",
    "synthesize_external_id",
]
