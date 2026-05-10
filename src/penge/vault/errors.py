"""Domain exceptions for the vault module."""

from __future__ import annotations


class VaultError(Exception):
    """Base class for all vault-related errors."""


class OCRError(VaultError):
    """Raised when OCR extraction fails irrecoverably."""


class FilerError(VaultError):
    """Raised when filing a document into the vault tree fails."""
