"""End-to-end report generation entry point.

Usage::

    uv run python -m penge.ops.report.generate --month 2026-04 --out reports/

Writes ``reports/2026-04/report.md`` and ``reports/2026-04/report.pdf``
plus the embedded PNG charts side-by-side. The directory layout is
intentionally month-scoped so a year of reports is trivially zippable
for the Nextcloud sync target referenced in the issue.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from .data import load_report_data
from .markdown import render_markdown
from .model import ReportData
from .pdf import render_pdf

if TYPE_CHECKING:
    from collections.abc import Sequence

log = logging.getLogger("penge.ops.report")

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def generate_report(
    month: str,
    out_root: Path,
    *,
    data: ReportData | None = None,
) -> tuple[Path, Path]:
    """Generate the monthly report.

    Args:
        month: ISO month string ``YYYY-MM``.
        out_root: Root output directory. The generator writes under
            ``out_root / month``.
        data: Optional pre-built :class:`ReportData`. When ``None``
            (the default), data is loaded from the marts via
            :func:`penge.ops.report.data.load_report_data`. Tests
            inject a synthetic payload to keep the run hermetic.

    Returns:
        ``(markdown_path, pdf_path)``.
    """

    if not _MONTH_RE.match(month):
        raise ValueError(f"month must match YYYY-MM, got {month!r}")

    payload = data if data is not None else load_report_data(month)
    out_dir = out_root / month
    out_dir.mkdir(parents=True, exist_ok=True)

    md_body = render_markdown(payload, out_dir)
    md_path = out_dir / "report.md"
    md_path.write_text(md_body, encoding="utf-8")

    pdf_path = render_pdf(payload, out_dir)
    return md_path, pdf_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="penge.ops.report.generate",
        description="Generate the Penge monthly PDF + Markdown report.",
    )
    parser.add_argument("--month", required=True, help="ISO month, e.g. 2026-04")
    parser.add_argument(
        "--out",
        default="reports",
        type=Path,
        help="Output root directory (default: reports/)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Log at DEBUG (default: INFO)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
    )
    try:
        md_path, pdf_path = generate_report(args.month, args.out)
    except ValueError as exc:
        log.error("%s", exc)
        return 2
    log.info("wrote %s", md_path)
    log.info("wrote %s", pdf_path)
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
