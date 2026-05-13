"""Shared :class:`decimal.Decimal` coercion helpers for the sim package.

Every sim sub-module accepts user-supplied numbers (from CSV rows,
scenario YAML, Pydantic models) and needs to coerce them into
``Decimal`` while rejecting NaN / Infinity and unconvertible inputs.

Some sim sub-modules previously carried their own ``_to_decimal``
helper, which risked drift in validation/error messages.  This module
is the single canonical implementation, re-exported as ``_to_decimal``
by callers (e.g. ``cashflow`` and ``liquid``) that retain the leading
underscore for backwards compatibility with their existing imports.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

__all__ = ["to_decimal"]


def to_decimal(v: object) -> Decimal:
    """Coerce *v* to :class:`Decimal` and reject NaN / Infinity values.

    Raises:
        ValueError: If *v* cannot be coerced or yields a non-finite
            :class:`Decimal` (NaN, +Inf, -Inf).
    """
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"cannot convert {v!r} to Decimal") from exc
    if not d.is_finite():
        raise ValueError(f"value must be finite, got {v!r}")
    return d
