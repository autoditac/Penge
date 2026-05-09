"""Pure parsing logic for the PFA Pensionsoversigt PDF.

Two extraction paths:

1. **pdfplumber** (default) — works on PFA's normal digital
   statements which embed text directly. Tables are extracted
   via ``page.extract_tables()`` and full-page text via
   ``page.extract_text()``.
2. **OCR fallback** — used when pdfplumber returns no text
   (scanned or image-only PDFs). Pages are rasterised with
   ``pdf2image`` and run through ``pytesseract`` with the
   Danish + German language packs (some expat statements have
   German addenda). The OCR result feeds the same row-level
   helpers as path #1.

The pure helpers (``_parse_dk_number``, ``_parse_dk_date``,
``synthesize_external_id``, ``parse_holdings_rows``,
``parse_scheme_rows``) operate on already-extracted strings and
are the unit-test surface — no PDF or OCR dependency required.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING

from penge.ingest.pfa.constants import (
    AS_OF_RE,
    DK_DATE_RE,
    EXTERNAL_ID_HASH_LEN,
    EXTERNAL_ID_PREFIX,
    PERIOD_RE,
    POLICY_NR_RE,
    SCHEME_HEADER_MAP,
)
from penge.ingest.pfa.models import (
    ParsedContribution,
    ParsedHolding,
    ParsedPensionsoversigt,
    ParsedScheme,
)

if TYPE_CHECKING:
    pass

log = logging.getLogger("penge.ingest.pfa.parser")

# --- minimum text length below which we treat a PDF as image-only ----------
#
# A typical Pensionsoversigt has ~3-5k characters of text once tables are
# extracted; if pdfplumber gets back less than this it usually means the
# PDF is a scanned image (no embedded text) or heavily image-based and
# we should fall back to OCR.
_MIN_EMBEDDED_TEXT_LEN = 200

# --- minimum row width for a row to be considered a table row -------------
_MIN_ROW_LEN = 2

# --- coarse OCR cell-grouping x-gap, in pixels -----------------------------
# Word boxes more than this many pixels apart on the same OCR line are
# split into separate logical "cells". Tuned for 300dpi A4 page rasters.
_OCR_CELL_GAP_PX = 80


# --- locale parsers --------------------------------------------------------


def _parse_dk_number(raw: str | None) -> Decimal | None:
    """Parse a DK-locale number (``1.234,56``) into a Decimal.

    Returns ``None`` for empty / placeholder cells (``"-"``, ``""``).
    A trailing ``" kr"`` or ``" DKK"`` suffix is allowed and
    stripped. A leading ``"-"`` (possibly inside a parenthesised
    accounting-style negative) is preserved.
    """

    if raw is None:
        return None
    s = raw.strip()
    if not s or s == "-":
        return None
    # Accounting-style negatives: ``(1.234,56)``.
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1].strip()
    # Strip optional currency / unit suffix.
    s = re.sub(r"\s*(?:kr\.?|DKK)\s*$", "", s, flags=re.IGNORECASE)
    # DK locale: "." is thousands, "," is decimal.
    s = s.replace(".", "").replace(",", ".")
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    return -value if negative else value


def _parse_dk_date(raw: str | None) -> date | None:
    """Parse ``31.12.2025`` into a ``date``."""

    if raw is None:
        return None
    m = DK_DATE_RE.search(raw)
    if not m:
        return None
    day, month, year = m.groups()
    try:
        return datetime.strptime(f"{day}.{month}.{year}", "%d.%m.%Y").date()
    except ValueError:
        return None


def _parse_dk_percent(raw: str | None) -> Decimal | None:
    """Parse ``"42,49 %"`` into ``Decimal("42.49")``."""

    if raw is None:
        return None
    s = raw.strip().replace("%", "").strip()
    return _parse_dk_number(s)


# --- external-id synthesis -------------------------------------------------


def synthesize_external_id(
    *,
    policy_number: str,
    scheme_kind: str,
    sub_policy_id: str,
    txn_kind: str,
    period_to: date,
    detail: str,
) -> str:
    """Build a deterministic per-account dedup key for a PFA transaction.

    PFA statements do not surface per-transaction ids, so the loader
    synthesises one from stable, identifying fields. The same set of
    inputs always produces the same external_id, which is exactly
    what ``ux_transaction__account_id_external_id`` needs for
    re-running an ingest of the same statement to be a no-op.
    """

    payload = "|".join(
        (
            policy_number,
            scheme_kind,
            sub_policy_id,
            txn_kind,
            period_to.isoformat(),
            detail,
        )
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{EXTERNAL_ID_PREFIX}{digest[:EXTERNAL_ID_HASH_LEN]}"


# --- row-level helpers (pure) ----------------------------------------------


def parse_holdings_rows(
    rows: Iterable[Sequence[str | None]],
) -> tuple[ParsedHolding, ...]:
    """Decode an ``Investeringsprofil`` table into ``ParsedHolding`` rows.

    Expected column order, matching PFA's PDF layout::

        | Fund name | Andel (%) | Andele | Markedsvaerdi (DKK) |

    Rows that don't contain a numeric market-value cell are skipped
    (covers footer rows, sub-totals like ``Kontant"`` cash sweep,
    and blank rows pdfplumber sometimes emits between sections).
    """

    out: list[ParsedHolding] = []
    for row in rows:
        if len(row) < _MIN_ROW_LEN:
            continue
        name = (row[0] or "").strip()
        if not name:
            continue
        # Drop totals / non-fund rows. PFA prints "I alt" and the
        # fund name "Total" on summary rows.
        if name.lower().startswith(("i alt", "total", "subtotal")):
            continue
        # Find the market_value cell - last non-empty numeric.
        mv: Decimal | None = None
        for cell in reversed(row[1:]):
            mv = _parse_dk_number(cell)
            if mv is not None:
                break
        if mv is None:
            continue
        # Allocation % and quantity are optional and positional.
        allocation = _parse_dk_percent(row[1] if len(row) > 1 else None)
        qty = _parse_dk_number(row[2] if len(row) > _MIN_ROW_LEN else None)
        out.append(
            ParsedHolding(
                fund_name=name,
                allocation_pct=allocation,
                quantity=qty,
                market_value_dkk=mv,
            )
        )
    return tuple(out)


def _detect_scheme_kind(label: str) -> str | None:
    """Return the canonical ``account.kind`` for a PFA scheme header.

    PFA prints headers like ``"Aldersopsparing"``, ``"Ratepension"``,
    ``"Livsvarig livrente"``. Lower-cased prefix match against
    ``SCHEME_HEADER_MAP``.
    """

    norm = label.strip().lower()
    # Prefer the longest matching prefix so ``"livsvarig livrente"``
    # wins over ``"livrente"``.
    for header in sorted(SCHEME_HEADER_MAP, key=len, reverse=True):
        if norm.startswith(header):
            return SCHEME_HEADER_MAP[header]
    return None


def parse_scheme_rows(
    rows: Iterable[Sequence[str | None]],
    *,
    sub_policy_id: str = "",
) -> ParsedScheme | None:
    """Decode the financial-summary table for one scheme.

    Expected layout, matching PFA's PDF::

        | Primo (Opening)              | <amount> |
        | Indbetaling - Arbejdsgiver   | <amount> |
        | Indbetaling - Privat         | <amount> |
        | Afkast                       | <amount> |
        | Omkostninger                 | <amount> |
        | PAL-skat                     | <amount> |
        | Udbetaling                   | <amount> |   (optional)
        | Ultimo (Closing)             | <amount> |

    The first row's first cell carries the scheme header (e.g.
    ``"Aldersopsparing"``); ``sub_policy_id`` is forwarded straight
    into the returned ``ParsedScheme`` and lets the caller
    disambiguate two schemes of the same kind under one policy.

    Returns ``None`` when the scheme header is unrecognised — the
    caller can then fall through to the next candidate table.
    """

    materialised = [list(r) for r in rows]
    if not materialised:
        return None

    # Header: first non-empty cell of the first row.
    header_cells = [c for c in materialised[0] if c]
    if not header_cells:
        return None
    scheme_kind = _detect_scheme_kind(header_cells[0])
    if scheme_kind is None:
        return None

    opening = closing = Decimal("0")
    return_dkk = fees_dkk = pal_skat = Decimal("0")
    contributions: list[ParsedContribution] = []

    for row in materialised[1:]:
        if not row:
            continue
        label = (row[0] or "").strip().lower()
        if not label:
            continue
        amount = _first_number(row[1:])
        if amount is None:
            continue
        opening, closing, return_dkk, fees_dkk, pal_skat = _apply_summary_row(
            label,
            amount,
            opening=opening,
            closing=closing,
            return_dkk=return_dkk,
            fees_dkk=fees_dkk,
            pal_skat=pal_skat,
            contributions=contributions,
        )

    return ParsedScheme(
        scheme_kind=scheme_kind,
        sub_policy_id=sub_policy_id,
        opening_balance_dkk=opening,
        closing_balance_dkk=closing,
        contributions=tuple(contributions),
        return_dkk=return_dkk,
        fees_dkk=fees_dkk,
        pal_skat_dkk=pal_skat,
    )


def _classify_contribution_source(label: str) -> str:
    """Map a contribution-row label to ``"employer"`` / ``"employee"``.

    PFA's exact strings vary slightly between policy templates;
    the parser handles the common variants.
    """

    if "arbejdsgiver" in label or "employer" in label or "firma" in label:
        return "employer"
    if "privat" in label or "egen" in label or "employee" in label:
        return "employee"
    # Default to ``employee`` so an unknown label still flows
    # through; a downstream test will catch genuinely-broken inputs.
    return "employee"


def _apply_summary_row(
    label: str,
    amount: Decimal,
    *,
    opening: Decimal,
    closing: Decimal,
    return_dkk: Decimal,
    fees_dkk: Decimal,
    pal_skat: Decimal,
    contributions: list[ParsedContribution],
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Dispatch a single financial-summary line to the right bucket.

    Mutates ``contributions`` in place; returns the (possibly
    updated) tuple of running totals.
    """

    bucket = _classify_summary_label(label)
    if bucket == "opening":
        opening = amount
    elif bucket == "closing":
        closing = amount
    elif bucket == "contribution":
        contributions.append(
            ParsedContribution(source=_classify_contribution_source(label), amount_dkk=amount)
        )
    elif bucket == "return":
        return_dkk = amount
    elif bucket == "fees":
        # PFA prints fees as a positive-magnitude deduction; we keep
        # the sign as printed and let the loader negate when posting
        # the ``fee`` transaction.
        fees_dkk = amount
    elif bucket == "pal_skat":
        pal_skat = amount
    # 'unknown' or 'withdrawal' is silently ignored (withdrawals are
    # surfaced separately if/when PFA emits them on the statement).
    return opening, closing, return_dkk, fees_dkk, pal_skat


def _classify_summary_label(label: str) -> str:
    """Bucket a financial-summary row label into a canonical key.

    Returns one of ``opening`` / ``closing`` / ``contribution`` /
    ``return`` / ``fees`` / ``pal_skat`` / ``unknown``. Implemented
    as a prefix/substring rule table to keep the body within ruff's
    PLR0911 ceiling.
    """

    _PREFIX_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
        (("primo", "indgående", "indgaaende"), "opening"),
        (("ultimo", "udgående", "udgaaende"), "closing"),
        (("afkast",), "return"),
        (("omkostning", "gebyr", "administration"), "fees"),
    )
    for prefixes, bucket in _PREFIX_RULES:
        if label.startswith(prefixes):
            return bucket
    if "indbetaling" in label or "indbet." in label:
        return "contribution"
    if "pal" in label or "pension afkastskat" in label or "pensionsafkastskat" in label:
        return "pal_skat"
    return "unknown"


def _first_number(cells: Iterable[str | None]) -> Decimal | None:
    """Return the first cell that parses as a DK number, else ``None``."""

    for c in cells:
        n = _parse_dk_number(c)
        if n is not None:
            return n
    return None


# --- metadata extraction ---------------------------------------------------


def _parse_metadata(
    full_text: str,
) -> tuple[str, date, date | None, date | None]:
    """Extract policy_number, as_of, period_from, period_to from full text.

    Raises ``ValueError`` when neither a policy number nor an
    as-of date can be found — those are minimum requirements for
    addressing rows back to a unique account in the loader.
    """

    policy_match = POLICY_NR_RE.search(full_text)
    if not policy_match:
        raise ValueError("PFA statement is missing 'Policenr.' header")
    policy_number = policy_match.group(1).strip()

    as_of_match = AS_OF_RE.search(full_text)
    if not as_of_match:
        raise ValueError("PFA statement is missing 'Pr. <date>' header")
    as_of = _parse_dk_date(as_of_match.group(1))
    if as_of is None:  # pragma: no cover  - regex guarantees parseable
        raise ValueError("PFA 'Pr.' header carries an unparseable date")

    period_from = period_to = None
    period_match = PERIOD_RE.search(full_text)
    if period_match:
        period_from = _parse_dk_date(period_match.group(1))
        period_to = _parse_dk_date(period_match.group(2))

    return policy_number, as_of, period_from, period_to


# --- entry point: PDF -> ParsedPensionsoversigt ----------------------------


def parse_pensionsoversigt(
    pdf_path: str | Path,
    *,
    allow_ocr: bool = True,
) -> ParsedPensionsoversigt:
    """Open *pdf_path* and return a fully parsed Pensionsoversigt.

    When pdfplumber returns less than ``_MIN_EMBEDDED_TEXT_LEN``
    characters of embedded text and ``allow_ocr=True``, the
    function falls back to the Tesseract OCR path.
    """

    pdf_path = Path(pdf_path)
    text, tables = _extract_text_and_tables_via_pdfplumber(pdf_path)
    extracted_via = "pdfplumber"
    if len(text) < _MIN_EMBEDDED_TEXT_LEN:
        if not allow_ocr:
            raise ValueError(f"PFA PDF {pdf_path.name} has no embedded text and OCR is disabled")
        log.info("PFA PDF %s has no embedded text; falling back to OCR", pdf_path.name)
        text, tables = _extract_text_and_tables_via_ocr(pdf_path)
        extracted_via = "ocr"

    policy_number, as_of, period_from, period_to = _parse_metadata(text)
    schemes = _build_schemes(tables)
    return ParsedPensionsoversigt(
        policy_number=policy_number,
        as_of=as_of,
        period_from=period_from,
        period_to=period_to,
        schemes=schemes,
        extracted_via=extracted_via,
    )


# Public alias matching the Growney connector for symmetry.
parse_pdf = parse_pensionsoversigt


# --- pdfplumber path -------------------------------------------------------


def _extract_text_and_tables_via_pdfplumber(
    pdf_path: Path,
) -> tuple[str, list[list[list[str | None]]]]:
    """Extract full-page text and per-page tables via pdfplumber.

    pdfplumber is imported lazily so users who only need the pure
    helpers can run without installing the ``parsers`` group.
    """

    import pdfplumber

    text_parts: list[str] = []
    tables: list[list[list[str | None]]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
            for raw_table in page.extract_tables() or []:
                rows = [[(c or "").strip() or None for c in row] for row in raw_table]
                if rows:
                    tables.append(rows)
    return "\n".join(text_parts), tables


# --- OCR fallback ----------------------------------------------------------


def _extract_text_and_tables_via_ocr(
    pdf_path: Path,
) -> tuple[str, list[list[list[str | None]]]]:
    """Rasterise *pdf_path* and run Tesseract OCR (DA+DEU).

    Tesseract is run in TSV mode so we can recover a coarse
    table structure from word-level bounding boxes — sufficient
    for PFA's wide, well-spaced layout. ``pdf2image``,
    ``pytesseract`` and ``Pillow`` are imported lazily.
    """

    import pdf2image
    import pytesseract

    text_parts: list[str] = []
    tables: list[list[list[str | None]]] = []
    images = pdf2image.convert_from_path(str(pdf_path), dpi=300)
    for image in images:
        # Single OCR pass per page: the TSV contains every word's
        # text plus its bounding box, so we use it both to rebuild
        # ``page_text`` and to recover row structure.
        data = pytesseract.image_to_data(
            image,
            lang="dan+deu",
            output_type=pytesseract.Output.DICT,
        )
        page_text = _ocr_data_to_text(data)
        text_parts.append(page_text)
        tables.extend(_ocr_words_to_tables(data))
    return "\n".join(text_parts), tables


def _ocr_data_to_text(data: dict[str, list[object]]) -> str:
    """Reconstruct page text from a Tesseract TSV result.

    Words are grouped by their ``(block_num, par_num, line_num)``
    key so the resulting string preserves Tesseract's natural line
    ordering. This avoids running ``image_to_string`` separately,
    halving OCR runtime per page.
    """

    def _as_int(value: object) -> int:
        if isinstance(value, int):
            return value
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return 0

    line_nums = data.get("line_num", [])
    block_nums = data.get("block_num", [])
    par_nums = data.get("par_num", [])
    lefts = data.get("left", [])
    texts = data.get("text", [])
    by_line: dict[tuple[int, int, int], list[tuple[int, int, str]]] = {}
    for i in range(len(texts)):
        word = str(texts[i]).strip()
        if not word:
            continue
        key = (
            _as_int(block_nums[i]) if i < len(block_nums) else 0,
            _as_int(par_nums[i]) if i < len(par_nums) else 0,
            _as_int(line_nums[i]) if i < len(line_nums) else 0,
        )
        x = _as_int(lefts[i]) if i < len(lefts) else 0
        # ``i`` is the tiebreaker: words at the same ``x`` retain
        # the order Tesseract emitted them.
        by_line.setdefault(key, []).append((x, i, word))
    return "\n".join(
        " ".join(word for _, _, word in sorted(by_line[key])) for key in sorted(by_line)
    )


def _ocr_words_to_tables(
    data: dict[str, list[object]],
) -> list[list[list[str | None]]]:
    """Group Tesseract word-boxes into tables, one per ``block_num``.

    Tesseract assigns a different ``block_num`` to each layout
    region on a page (a paragraph, a table, a header). Splitting
    on ``block_num`` lets the downstream scheme detector work on
    each region independently — necessary when a page contains
    both a metadata header and a financial-summary table. Within
    a block, words are grouped into rows by ``(par_num,
    line_num)``; cells inside a row are split on a coarse x-gap
    heuristic. The returned structure mimics what pdfplumber's
    ``extract_tables`` produces, so downstream helpers can be
    shared between the two extraction paths.
    """

    def _as_int(value: object) -> int:
        # Tesseract returns numeric columns as ``list[int]`` at runtime
        # but the wrapper types them as ``list[object]``; coerce safely.
        if isinstance(value, int):
            return value
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return 0

    by_block: dict[int, dict[tuple[int, int], list[tuple[int, int, str]]]] = {}
    line_nums = data.get("line_num", [])
    block_nums = data.get("block_num", [])
    par_nums = data.get("par_num", [])
    lefts = data.get("left", [])
    texts = data.get("text", [])
    for i in range(len(texts)):
        word = str(texts[i]).strip()
        if not word:
            continue
        block = _as_int(block_nums[i]) if i < len(block_nums) else 0
        line_key = (
            _as_int(par_nums[i]) if i < len(par_nums) else 0,
            _as_int(line_nums[i]) if i < len(line_nums) else 0,
        )
        x = _as_int(lefts[i]) if i < len(lefts) else 0
        by_block.setdefault(block, {}).setdefault(line_key, []).append((x, i, word))

    tables: list[list[list[str | None]]] = []
    for block in sorted(by_block):
        rows: list[list[str | None]] = []
        for key in sorted(by_block[block]):
            words = sorted(by_block[block][key])
            # Group adjacent words into logical "cells" using a coarse
            # x-gap heuristic.
            cells: list[list[str]] = [[]]
            prev_x: int | None = None
            for x, _idx, word in words:
                if prev_x is not None and (x - prev_x) > _OCR_CELL_GAP_PX:
                    cells.append([])
                cells[-1].append(word)
                prev_x = x + len(word) * 12  # rough char-width estimate
            rows.append([" ".join(c) if c else None for c in cells])
        if rows:
            tables.append(rows)
    return tables


# --- table dispatch --------------------------------------------------------


def _build_schemes(
    tables: list[list[list[str | None]]],
) -> tuple[ParsedScheme, ...]:
    """Group financial-summary + holdings tables into ``ParsedScheme``s.

    Strategy: for each table whose first row carries a recognised
    PFA scheme header, build a ``ParsedScheme`` from it. Subsequent
    tables that begin with a typical financial-summary label
    (``Indbetaling`` / ``Afkast`` / ``Ultimo`` / …) are treated as
    *continuations* of the most recent scheme — necessary because
    PFA frequently splits a single scheme across two pages, and
    pdfplumber returns the halves as separate tables. Any
    ``Investeringsprofil`` (holdings) table is then attached to the
    most recent scheme. This matches PFA's own PDF section ordering.
    """

    _CONTINUATION_PREFIXES = (
        "primo",
        "indbetaling",
        "indbet.",
        "afkast",
        "omkostning",
        "gebyr",
        "administration",
        "pal",
        "pension afkastskat",
        "pensionsafkastskat",
        "ultimo",
        "udgående",
        "udgaaende",
    )

    schemes: list[ParsedScheme] = []
    counter: dict[str, int] = {}
    last_scheme_idx: int | None = None
    for rows in tables:
        if not rows:
            continue
        header = " ".join((c or "") for c in rows[0]).strip()
        # Investeringsprofil tables: header contains "Investerings".
        if "investerings" in header.lower():
            holdings = parse_holdings_rows(rows[1:])
            if last_scheme_idx is not None and holdings:
                target = schemes[last_scheme_idx]
                schemes[last_scheme_idx] = target.model_copy(update={"holdings": holdings})
            continue
        first_cell = (rows[0][0] or "").strip() if rows[0] else ""
        kind = _detect_scheme_kind(first_cell)
        if kind is None:
            # Continuation of the previous scheme? Only if the first
            # cell looks like a known summary label.
            label = first_cell.lower()
            if last_scheme_idx is not None and label.startswith(_CONTINUATION_PREFIXES):
                target = schemes[last_scheme_idx]
                # Re-run the summary parser over the union of the
                # original rows and the continuation rows. We
                # synthesise a header so ``parse_scheme_rows`` can
                # treat it as one logical block.
                synthetic_header: list[str | None] = [target.scheme_kind, None]
                merged_rows = [synthetic_header, *_target_summary_rows(target), *rows]
                merged = parse_scheme_rows(merged_rows, sub_policy_id=target.sub_policy_id)
                if merged is not None:
                    schemes[last_scheme_idx] = merged.model_copy(
                        update={"holdings": target.holdings}
                    )
            continue
        counter[kind] = counter.get(kind, 0) + 1
        sub_id = str(counter[kind])
        scheme = parse_scheme_rows(rows, sub_policy_id=sub_id)
        if scheme is None:  # pragma: no cover  - covered by _detect_scheme_kind
            continue
        schemes.append(scheme)
        last_scheme_idx = len(schemes) - 1
    return tuple(schemes)


def _target_summary_rows(scheme: ParsedScheme) -> list[list[str | None]]:
    """Rebuild raw summary rows from a ``ParsedScheme``.

    Used by ``_build_schemes`` to merge a continuation table with
    an existing scheme by re-running ``parse_scheme_rows`` over the
    concatenation. Only the fields ``parse_scheme_rows`` consumes
    are emitted; numeric formatting matches the parser's accepted
    Danish style.
    """

    def _fmt(amount: Decimal) -> str:
        return f"{amount:.2f}".replace(".", ",")

    rows: list[list[str | None]] = []
    if scheme.opening_balance_dkk:
        rows.append(["Primo", _fmt(scheme.opening_balance_dkk)])
    for c in scheme.contributions:
        label = "Indbetaling - Arbejdsgiver" if c.source == "employer" else "Indbetaling - Privat"
        rows.append([label, _fmt(c.amount_dkk)])
    if scheme.return_dkk:
        rows.append(["Afkast", _fmt(scheme.return_dkk)])
    if scheme.fees_dkk:
        rows.append(["Omkostninger", _fmt(scheme.fees_dkk)])
    if scheme.pal_skat_dkk:
        rows.append(["PAL-skat", _fmt(scheme.pal_skat_dkk)])
    if scheme.closing_balance_dkk:
        rows.append(["Ultimo", _fmt(scheme.closing_balance_dkk)])
    return rows
