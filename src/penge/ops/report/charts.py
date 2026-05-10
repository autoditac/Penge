"""Static chart rendering for the monthly report.

Each helper writes a PNG to ``out_dir`` and returns the relative file
name. The Markdown renderer embeds the PNG via ``![alt](chart.png)``;
the PDF renderer ingests the same file via ``reportlab.platypus.Image``.

matplotlib is imported lazily so importing :mod:`penge.ops.report`
does not pull the (heavy) plotting stack on environments that only
need the model classes.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

# Eagerly import Pillow before any downstream code reaches for matplotlib.
# In some test environments (pytest collecting streamlit + pdf2image
# alongside our charts) Pillow's plugin registry is left in a state
# where ``Image.SAVE`` is empty even though ``Image._initialized == 2``.
# Touching ``PIL.Image`` here, before matplotlib's lazy PIL import,
# ensures the PNG plugin registers cleanly and ``fig.savefig("foo.png")``
# does not raise ``KeyError: 'PNG'`` later.
from PIL import Image as _PILImage  # noqa: F401
from PIL import PngImagePlugin as _PILPng  # noqa: F401

from penge.ops.report.redact import redact_text


def _safe_label(label: str) -> str:
    """Strip PII and control chars from a chart label.

    Chart labels are baked into the rasterized PNG, so unlike the
    Markdown / PDF text streams they cannot be retroactively cleaned.
    We redact aggressively here as defence in depth.
    """

    return redact_text(label).replace("\n", " ").strip()


def _setup_matplotlib() -> Any:
    """Configure matplotlib for headless use and return the ``pyplot`` module."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Belt-and-braces: re-register the PNG plugin if the SAVE/OPEN
    # registries were emptied by another import. See the module-level
    # comment for context.
    from PIL import Image, PngImagePlugin

    if "PNG" not in Image.SAVE:
        Image.register_save("PNG", PngImagePlugin._save)
        Image.register_extension("PNG", ".png")
    if "PNG" not in Image.OPEN:
        Image.register_open("PNG", PngImagePlugin.PngImageFile, PngImagePlugin._accept)

    return plt


def render_sparkline(
    out_dir: Path,
    series: list[tuple[str, Decimal]],
    *,
    filename: str = "net_worth_sparkline.png",
) -> str:
    """Render a 12-month net-worth sparkline. Returns the relative filename.

    The chart is intentionally minimal — no grid, single line, tight
    axis labels — so it embeds cleanly into both the Markdown TOC
    flow and the PDF Story.
    """

    plt = _setup_matplotlib()
    out_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(6.4, 1.8))
    if series:
        xs = [m for m, _ in series]
        ys = [float(v) for _, v in series]
        ax.plot(xs, ys, marker="o", linewidth=1.5)
        ax.set_xticks(range(len(xs)))
        ax.set_xticklabels(xs, rotation=45, ha="right", fontsize=7)
        ax.tick_params(axis="y", labelsize=7)
        ax.grid(visible=True, axis="y", linestyle=":", alpha=0.4)
    else:
        ax.text(0.5, 0.5, "no data", ha="center", va="center", transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])

    ax.set_title("Net worth, EUR (last 12 months)", fontsize=9)
    fig.tight_layout()

    path = out_dir / filename
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return filename


def render_pie(
    out_dir: Path,
    slices: list[tuple[str, Decimal, Decimal]],
    *,
    title: str,
    filename: str,
) -> str:
    """Render a pie chart for an allocation breakdown."""

    plt = _setup_matplotlib()
    out_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(4.2, 4.2))
    if slices:
        # Labels are baked into the PNG pixels — redact every label so
        # PII can never leak via the rendered image even if a caller
        # passes an un-redacted source string.
        labels = [_safe_label(label) for label, _, _ in slices]
        sizes = [float(value) for _, value, _ in slices]
        ax.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=90, textprops={"fontsize": 8})
        ax.set_aspect("equal")
    else:
        ax.text(0.5, 0.5, "no data", ha="center", va="center", transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    path = out_dir / filename
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return filename


def render_bar(
    out_dir: Path,
    bars: list[tuple[str, Decimal]],
    *,
    title: str,
    filename: str,
) -> str:
    """Render a horizontal bar chart (used for cashflow categories)."""

    plt = _setup_matplotlib()
    out_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    if bars:
        # Same defence-in-depth as render_pie: redact y-tick labels so
        # the rendered PNG cannot leak PII.
        labels = [_safe_label(label) for label, _ in bars]
        values = [float(v) for _, v in bars]
        positions = list(range(len(labels)))
        ax.barh(positions, values)
        ax.set_yticks(positions)
        ax.set_yticklabels(labels, fontsize=8)
        ax.tick_params(axis="x", labelsize=7)
        ax.axvline(0, color="black", linewidth=0.6)
        ax.invert_yaxis()
    else:
        ax.text(0.5, 0.5, "no data", ha="center", va="center", transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    path = out_dir / filename
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return filename
