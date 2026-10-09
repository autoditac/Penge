"""Invariants for the source-grain synthetic household test data."""

from decimal import Decimal

from tests.household.fixtures import (
    ACCOUNTS,
    BANK_ENTRIES,
    FX_RATES,
    PAYPAL_DETAILS,
    PAYPAL_IDENTIFICATION_HASH_ALTERNATES,
    PAYPAL_PRIMARY_IDENTIFICATION_HASH,
    PAYPAL_RENEWED_TRANSACTION_IDS,
    PAYPAL_SESSION_UIDS,
    PAYPAL_SOURCE_ACCOUNT_ID,
)


def test_bank_entries_have_unique_external_ids_and_known_accounts() -> None:
    keys = [entry.key for entry in BANK_ENTRIES]
    account_keys = {account.key for account in ACCOUNTS}

    assert len(keys) == len(set(keys))
    assert all(entry.account_key in account_keys for entry in BANK_ENTRIES)


def test_paypal_examples_conserve_the_bank_grain_amounts() -> None:
    entries = {entry.key: entry for entry in BANK_ENTRIES}
    totals: dict[str, Decimal] = {}
    for detail in PAYPAL_DETAILS:
        totals[detail.bank_entry_key] = (
            totals.get(detail.bank_entry_key, Decimal("0")) + detail.amount
        )

    assert totals["paypal-direct"] == entries["paypal-direct"].amount
    assert totals["paypal-aggregate"] == entries["paypal-aggregate"].amount
    assert totals["paypal-delayed"] == entries["paypal-delayed"].amount
    eur_usd_rate = next(rate for _, currency, rate in FX_RATES if currency == "USD")
    assert totals["paypal-refund"] / eur_usd_rate == entries["paypal-refund"].amount


def test_transfer_pair_is_equal_at_the_synthetic_ecb_rate() -> None:
    entries = {entry.key: entry for entry in BANK_ENTRIES}
    eur_dkk_rate = next(rate for _, currency, rate in FX_RATES if currency == "DKK")

    assert entries["transfer-out"].value_date == entries["transfer-in"].value_date
    assert entries["transfer-out"].amount * eur_dkk_rate == -entries["transfer-in"].amount


def test_marketplace_fixture_reuses_a_vendor_across_mixed_purchase_contexts() -> None:
    entries = {entry.key: entry for entry in BANK_ENTRIES}
    supermarket = entries["supermarket-split"]
    prepared_food = entries["mixed-merchant-purchase"]

    assert supermarket.counterparty == prepared_food.counterparty == "North Market"
    assert supermarket.description != prepared_food.description


def test_paypal_renewal_fixture_keeps_primary_identity_distinct_from_session_ids() -> None:
    assert PAYPAL_SESSION_UIDS[0] != PAYPAL_SESSION_UIDS[1]
    assert PAYPAL_IDENTIFICATION_HASH_ALTERNATES[0] != PAYPAL_IDENTIFICATION_HASH_ALTERNATES[1]
    assert PAYPAL_PRIMARY_IDENTIFICATION_HASH not in PAYPAL_SESSION_UIDS
    assert f"DE:{PAYPAL_PRIMARY_IDENTIFICATION_HASH}" == PAYPAL_SOURCE_ACCOUNT_ID
    assert all(uid not in PAYPAL_SOURCE_ACCOUNT_ID for uid in PAYPAL_SESSION_UIDS)
    assert all(
        alternate not in PAYPAL_SOURCE_ACCOUNT_ID
        for alternate in PAYPAL_IDENTIFICATION_HASH_ALTERNATES
    )
    direct_detail = next(
        detail for detail in PAYPAL_DETAILS if detail.entry_reference == "direct-purchase"
    )
    assert (
        direct_detail.transaction_id
        != PAYPAL_RENEWED_TRANSACTION_IDS[direct_detail.entry_reference]
    )


def test_paypal_detail_entry_references_are_stable_and_unique() -> None:
    entry_references = [detail.entry_reference for detail in PAYPAL_DETAILS]
    assert len(entry_references) == len(set(entry_references))
    assert all(detail.event_kind == "unknown" for detail in PAYPAL_DETAILS)


def test_first_eur_dkk_rate_is_after_the_missing_fx_entry() -> None:
    first_fx_date = min(as_of for as_of, currency, _ in FX_RATES if currency == "DKK")
    missing_fx_entry = next(entry for entry in BANK_ENTRIES if entry.key == "before-first-fx")

    assert missing_fx_entry.value_date < first_fx_date
