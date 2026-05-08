"""PFA pension ingest connector.

PFA Pension is a Danish pension provider. Account holders receive
periodic *Pensionsoversigt* (pension overview) PDFs that summarise:

- one or more sub-policies, each scoped to a Danish pension regime
  (``aldersopsparing``, ``ratepension``, ``livrente`` /
  ``livrente_livsvarig``);
- the policy's investment profile (PFA Plus by default), expressed
  as a list of fund holdings with market value in DKK;
- contributions year-to-date (employer + employee), the gross /
  net return, fees, and PAL-skat (Danish pension capital tax,
  currently 15.3% — applied at the policy level by PFA itself).

This connector parses those PDFs and upserts the contents into the
operational schema. The text-extraction path uses ``pdfplumber``;
when a statement is a scanned image (no embedded text), the parser
falls back to Tesseract OCR with the Danish + German language
packs (some PFA statements include German-language addenda for
expat policy holders).

Public API mirrors the Nordnet / Growney connectors:

- pure parser surface (``parse_pensionsoversigt``,
  ``parse_holdings_rows``, ``parse_scheme_rows``,
  ``synthesize_external_id``);
- loader entrypoints (``load_files``, ``load_records``);
- ``penge-pfa`` CLI.

See ``docs/connectors/pfa.md`` for the field-mapping table and
runbook.
"""

from penge.ingest.pfa.constants import (
    ACCOUNT_KIND_ALDERSOPSPARING,
    ACCOUNT_KIND_LIVRENTE,
    ACCOUNT_KIND_RATEPENSION,
    PROVIDER,
    TXN_KIND_CONTRIBUTION,
    TXN_KIND_FEE,
    TXN_KIND_PAL_SKAT,
    TXN_KIND_RETURN,
    TXN_KIND_WITHDRAWAL,
)
from penge.ingest.pfa.loader import LoadResult, load_files, load_records
from penge.ingest.pfa.models import (
    ParsedContribution,
    ParsedHolding,
    ParsedPensionsoversigt,
    ParsedScheme,
)
from penge.ingest.pfa.parser import (
    parse_holdings_rows,
    parse_pensionsoversigt,
    parse_scheme_rows,
    synthesize_external_id,
)

__all__ = [
    "ACCOUNT_KIND_ALDERSOPSPARING",
    "ACCOUNT_KIND_LIVRENTE",
    "ACCOUNT_KIND_RATEPENSION",
    "PROVIDER",
    "TXN_KIND_CONTRIBUTION",
    "TXN_KIND_FEE",
    "TXN_KIND_PAL_SKAT",
    "TXN_KIND_RETURN",
    "TXN_KIND_WITHDRAWAL",
    "LoadResult",
    "ParsedContribution",
    "ParsedHolding",
    "ParsedPensionsoversigt",
    "ParsedScheme",
    "load_files",
    "load_records",
    "parse_holdings_rows",
    "parse_pensionsoversigt",
    "parse_scheme_rows",
    "synthesize_external_id",
]
