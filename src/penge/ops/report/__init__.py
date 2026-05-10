"""Monthly automated PDF + Markdown report (issue #50).

The generator is self-contained: it loads aggregated month-end data
from the dbt marts (when a database is reachable) and renders two
artefacts side-by-side under ``reports/{YYYY-MM}/``:

* ``report.md`` — Markdown, embedding PNG charts via relative path.
* ``report.pdf`` — pure-Python PDF (reportlab) embedding the same
  charts.

Sections, in order: header / net worth / cashflow / asset allocation
/ tax preview / FIRE projection snapshot / operations.

Privacy: every string field that lands in the report passes through
:func:`penge.ops.report.redact.redact_text`, which mirrors the regex
used by :mod:`penge.ops.sentry` and the MCP audit logger. No real
account numbers, names, or emails ever reach the rendered output.

See ``docs/runbook/monthly-report.md`` for the operator workflow and
the cron / systemd-timer scheduling pattern.
"""

from __future__ import annotations

from .generate import generate_report
from .model import ReportData

__all__ = ["ReportData", "generate_report"]
