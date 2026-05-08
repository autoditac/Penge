"""Identifier masking helpers.

The dashboard is read-only and runs locally, but the screen may still
be visible to bystanders, recorded by screen-share, or screenshot for
support. We therefore mask account identifiers by default and require
an explicit toggle to reveal them. See acceptance criterion
"No raw account numbers shown by default" in issue #25.
"""

from __future__ import annotations

# Number of trailing characters to keep visible when masking. Four is
# the convention used by banks and card issuers.
TAIL_VISIBLE = 4


def mask_iban(iban: str | None, *, reveal: bool = False) -> str:
    """Return an IBAN with all but the last 4 characters replaced by ``•``.

    Spaces are stripped first so an IBAN entered with formatting
    (``DK50 0040 0440 1162 43``) masks identically to its canonical
    form. Returns the empty string for ``None`` or empty input so it is
    safe to feed into a Streamlit table without further guarding.
    """
    if not iban:
        return ""
    compact = iban.replace(" ", "")
    if reveal:
        return compact
    if len(compact) <= TAIL_VISIBLE:
        return "•" * len(compact)
    return "•" * (len(compact) - TAIL_VISIBLE) + compact[-TAIL_VISIBLE:]


def mask_account_name(name: str | None, *, reveal: bool = False) -> str:
    """Return an account display name with the bracketed last-4 suffix masked.

    Loaders frequently store the last 4 digits of an account number in
    the display name (``"Aktiesparekonto (1162)"``). This helper masks
    that suffix without touching the human-readable label.
    """
    if not name:
        return ""
    if reveal:
        return name
    open_idx = name.rfind("(")
    close_idx = name.rfind(")")
    if open_idx == -1 or close_idx <= open_idx:
        return name
    inner = name[open_idx + 1 : close_idx]
    if not inner.isdigit():
        return name
    masked = "•" * len(inner)
    return f"{name[:open_idx]}({masked}){name[close_idx + 1 :]}"
