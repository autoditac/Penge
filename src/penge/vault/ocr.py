"""Tesseract OCR wrapper for vault documents.

The vault watcher needs searchable text out of every incoming PDF —
embedded text where present, rasterised + OCR'd where not. We mirror
the strategy used by the PFA connector (see ``src/penge/ingest/pfa/
parser.py``):

1. Try ``pdfplumber`` for embedded text. If a page yields more than
   :data:`EMBEDDED_TEXT_THRESHOLD` characters we treat that page as
   already searchable and skip OCR for it.
2. Otherwise rasterise the page via ``pdf2image`` and run Tesseract
   with the configured language pack triple ``dan+deu+eng``.

Tesseract is a *system* binary — see the README for installation
instructions. The Python bindings (``pytesseract``, ``pdf2image``,
``Pillow``) are imported lazily so unit tests that mock OCR do not
require the heavy native deps to be present.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from penge.vault.errors import OCRError

log = logging.getLogger("penge.vault.ocr")

#: Tesseract language code. The vault assumes a DK/DE household so we
#: load Danish, German, and English packs by default. Override via the
#: ``--ocr-langs`` CLI flag or the :class:`OCRConfig` constructor.
DEFAULT_LANGS = "dan+deu+eng"

#: Pages with at least this much embedded text are *not* re-OCR'd. A
#: handful of layout glyphs (page numbers, footers) are excluded so
#: image-only pages still trigger the OCR fallback.
EMBEDDED_TEXT_THRESHOLD = 80


class OCRConfig(BaseModel):
    """Configuration for the vault OCR pipeline."""

    langs: str = Field(default=DEFAULT_LANGS, description="Tesseract --lang argument.")
    dpi: int = Field(default=300, ge=72, le=600, description="Rasterisation DPI.")


@dataclass(frozen=True)
class OCRResult:
    """Outcome of running OCR on a single document."""

    text: str
    pages: int
    extracted_via: str  # "embedded" | "ocr" | "mixed"


def extract_text(pdf_path: Path, config: OCRConfig | None = None) -> OCRResult:
    """Extract searchable text from *pdf_path*.

    Args:
        pdf_path: Path to a PDF file. Non-PDF inputs raise :class:`OCRError`.
        config: Optional :class:`OCRConfig`. Defaults to ``DEFAULT_LANGS``
            and 300 DPI.

    Returns:
        :class:`OCRResult` with the joined page text, page count, and
        which extraction path produced the text.

    Raises:
        OCRError: If the underlying tooling fails or the file is not
            a readable PDF.
    """

    if not pdf_path.is_file():
        raise OCRError(f"not a file: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise OCRError(f"unsupported file type for OCR: {pdf_path.suffix}")

    cfg = config or OCRConfig()

    embedded_pages, total_pages = _try_embedded(pdf_path)
    needs_ocr = [i for i, text in enumerate(embedded_pages) if len(text) < EMBEDDED_TEXT_THRESHOLD]

    if not needs_ocr:
        return OCRResult(
            text="\n".join(embedded_pages),
            pages=total_pages,
            extracted_via="embedded",
        )

    try:
        ocr_pages = _ocr_pages(pdf_path, page_indices=needs_ocr, cfg=cfg)
    except OCRError:
        raise
    except Exception as exc:
        raise OCRError(f"OCR failed for {pdf_path.name}: {exc}") from exc

    merged = list(embedded_pages)
    for idx, text in zip(needs_ocr, ocr_pages, strict=True):
        merged[idx] = text

    extracted_via = "ocr" if len(needs_ocr) == total_pages else "mixed"
    return OCRResult(text="\n".join(merged), pages=total_pages, extracted_via=extracted_via)


def _try_embedded(pdf_path: Path) -> tuple[list[str], int]:
    """Pull embedded text page-by-page via pdfplumber.

    Returns the per-page text list and the total page count. If
    pdfplumber is not installed (the optional ``parsers`` group is not
    present) we report every page as empty so the OCR path is taken.
    """

    try:
        import pdfplumber  # noqa: PLC0415 - lazy: heavy native dep
    except ImportError:
        log.info("vault.ocr.pdfplumber_missing path=%s", pdf_path)
        return [], _page_count(pdf_path)

    pages: list[str] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                pages.append((page.extract_text() or "").strip())
    except Exception as exc:
        raise OCRError(f"pdfplumber failed for {pdf_path.name}: {exc}") from exc
    return pages, len(pages)


def _page_count(pdf_path: Path) -> int:
    """Best-effort page count when pdfplumber is unavailable."""

    try:
        import pdf2image  # noqa: PLC0415 - lazy: heavy native dep
    except ImportError:
        return 1
    try:
        info = pdf2image.pdfinfo_from_path(str(pdf_path))
    except Exception:
        return 1
    pages = info.get("Pages", 1)
    return int(pages) if isinstance(pages, int | str) else 1


def _ocr_pages(pdf_path: Path, *, page_indices: list[int], cfg: OCRConfig) -> list[str]:
    """Rasterise the requested pages and run Tesseract on each."""

    import pdf2image  # noqa: PLC0415 - lazy: heavy native dep
    import pytesseract  # noqa: PLC0415 - lazy: ships no stubs

    images = pdf2image.convert_from_path(
        str(pdf_path),
        dpi=cfg.dpi,
        first_page=min(page_indices) + 1,
        last_page=max(page_indices) + 1,
    )
    offset = min(page_indices)
    out: list[str] = []
    for idx in page_indices:
        image = images[idx - offset]
        text = pytesseract.image_to_string(image, lang=cfg.langs)
        out.append(text.strip())
    return out
