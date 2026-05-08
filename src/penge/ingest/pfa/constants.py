"""Vocabulary and shared regexes for the PFA pension ingest.

These literals are the only string constants other modules
(loader, dbt staging, marts, tax modules) should match against.
"""

from __future__ import annotations

import re
from typing import Final

# --- provider --------------------------------------------------------------

PROVIDER: Final = "pfa"
"""``account.provider`` value for every PFA pension account."""

# --- account.kind vocabulary ----------------------------------------------
#
# Danish pension regimes. PFA statements use the Danish names
# verbatim, and the regime determines how SKAT taxes contributions
# and pay-outs:
#
# - **Aldersopsparing** — taxed on contribution (no deduction);
#   pay-outs (lump sum) are tax-free. Contribution cap applies.
# - **Ratepension** — deductible on contribution (capped); pay-outs
#   are taxed as personal income, in fixed instalments over ≥10y.
# - **Livrente** (livsvarig livrente) — deductible without cap;
#   pay-outs are taxed as personal income, paid for life.
#
# PAL-skat (15.3%) is levied on the *return* generated inside the
# scheme — by PFA, before crediting — for all three regimes.

ACCOUNT_KIND_ALDERSOPSPARING: Final = "aldersopsparing"
ACCOUNT_KIND_RATEPENSION: Final = "ratepension"
ACCOUNT_KIND_LIVRENTE: Final = "livrente"

ACCOUNT_KINDS: Final = frozenset(
    {
        ACCOUNT_KIND_ALDERSOPSPARING,
        ACCOUNT_KIND_RATEPENSION,
        ACCOUNT_KIND_LIVRENTE,
    }
)

# Mapping from the Danish header strings PFA emits to canonical kinds.
# Lower-cased on the parser side before lookup so case variations don't
# matter. ``Livsvarig livrente`` and ``Livrente`` are merged.
SCHEME_HEADER_MAP: Final[dict[str, str]] = {
    "aldersopsparing": ACCOUNT_KIND_ALDERSOPSPARING,
    "ratepension": ACCOUNT_KIND_RATEPENSION,
    "livrente": ACCOUNT_KIND_LIVRENTE,
    "livsvarig livrente": ACCOUNT_KIND_LIVRENTE,
}

# --- transaction.kind vocabulary ------------------------------------------

TXN_KIND_CONTRIBUTION: Final = "deposit"
"""Employer / employee contribution into a PFA scheme."""

TXN_KIND_WITHDRAWAL: Final = "withdrawal"
"""Pay-out from a PFA scheme (rate, lump sum, livrente instalment)."""

TXN_KIND_RETURN: Final = "dividend"
"""Investment return credited inside the scheme.

Re-uses the canonical ``dividend`` kind because PFA aggregates
all return components (interest, dividends, MTM gain/loss) into
a single line on the statement; ``dividend`` is the closest fit
in the existing vocabulary and is consistent with the Growney /
Nordnet conventions for crediting events.
"""

TXN_KIND_FEE: Final = "fee"
"""PFA-charged fee (Omkostninger / Administrationsomkostninger)."""

TXN_KIND_PAL_SKAT: Final = "tax"
"""Pensions-afkastskat (15.3%) deducted by PFA before crediting return.

The canonical ``tax`` kind is reused; ``transaction.description``
records the regime explicitly (``"PAL-skat"``) so the dbt model
and downstream tax reports can distinguish it.
"""

# --- instrument modelling --------------------------------------------------

PFA_FUND_TICKER_PREFIX: Final = "PFA:"
"""Synthesised ``instrument.ticker`` prefix for PFA Plus internal funds.

PFA's investment profile funds (e.g. ``PFA Plus AA``,
``PFA Globale Aktier``) are not exchange-listed and have no public
ISIN. We synthesise a stable ticker ``PFA:<slug>`` from the fund
name so the ``instrument`` table can model them like any other
holding without colliding with real ISIN-bearing securities.
"""

INSTRUMENT_KIND_FUND: Final = "fund"
"""``instrument.kind`` value for synthesised PFA Plus funds."""

# --- regexes ---------------------------------------------------------------

# DK locale numbers: ``1.234,56``, ``-2.500,00``, ``77,66 kr``.
DK_NUMBER_RE: Final = re.compile(
    r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?",
)

# DK dates: ``31.12.2025``.
DK_DATE_RE: Final = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")

# Policy number: ``Policenr.: 12-345-678`` or just digits.
POLICY_NR_RE: Final = re.compile(
    r"Policenr\.?:?\s*([0-9][0-9\-]{4,})",
    re.IGNORECASE,
)

# Snapshot date on the cover sheet: ``Pr. 31.12.2025`` or
# ``Opgjort pr. 31.12.2025``.
AS_OF_RE: Final = re.compile(
    r"(?:Opgjort\s+)?Pr\.\s*(\d{2}\.\d{2}\.\d{4})",
    re.IGNORECASE,
)

# Period: ``01.01.2025 - 31.12.2025``. Both hyphen-minus and EN DASH are
# accepted because PFA's typesetter has been seen to use either.
PERIOD_RE: Final = re.compile(
    "(\\d{2}\\.\\d{2}\\.\\d{4})\\s*[-\u2013]\\s*(\\d{2}\\.\\d{2}\\.\\d{4})"
)

# --- external-id synthesis -------------------------------------------------

EXTERNAL_ID_PREFIX: Final = "pfa:"
EXTERNAL_ID_HASH_LEN: Final = 16
"""SHA-256 truncation length for synthesised transaction external_ids.

16 hex chars → 64 bits. With the ``pfa:`` namespace this is more
than sufficient to avoid collisions across realistic statement
volumes (per ADR-0008's external_id discussion).
"""
