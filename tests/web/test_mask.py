"""Unit tests for ``penge.web.mask`` (issue #25 acceptance criterion).

Covers the masking contract for IBANs and account display names. No
DB or network — pure string transforms.
"""

from __future__ import annotations

from penge.web.mask import mask_account_name, mask_iban


class TestMaskIban:
    def test_masks_all_but_last_four(self) -> None:
        assert mask_iban("DK5000400440116243") == "••••••••••••••6243"

    def test_strips_spaces_before_masking(self) -> None:
        assert mask_iban("DK50 0040 0440 1162 43") == "••••••••••••••6243"

    def test_reveal_returns_compact_form(self) -> None:
        assert mask_iban("DK50 0040 0440 1162 43", reveal=True) == "DK5000400440116243"

    def test_none_returns_empty(self) -> None:
        assert mask_iban(None) == ""

    def test_empty_returns_empty(self) -> None:
        assert mask_iban("") == ""

    def test_short_iban_fully_masked(self) -> None:
        # Defensive: input shorter than the visible tail is fully masked
        # rather than leaking everything via the slice.
        assert mask_iban("AB12") == "••••"
        assert mask_iban("AB") == "••"


class TestMaskAccountName:
    def test_masks_trailing_digit_suffix(self) -> None:
        assert mask_account_name("Aktiesparekonto (1162)") == "Aktiesparekonto (••••)"

    def test_reveal_returns_input(self) -> None:
        assert mask_account_name("Aktiesparekonto (1162)", reveal=True) == "Aktiesparekonto (1162)"

    def test_no_parens_returns_input(self) -> None:
        assert mask_account_name("Aktiesparekonto") == "Aktiesparekonto"

    def test_non_digit_parens_left_alone(self) -> None:
        # We only mask numeric suffixes — labels like "Børnenes konto (joint)"
        # should stay intact.
        assert mask_account_name("Børnenes konto (joint)") == "Børnenes konto (joint)"

    def test_none_returns_empty(self) -> None:
        assert mask_account_name(None) == ""
