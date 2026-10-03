"""Enable Banking → household payment-detail loader for PayPal.

Unlike the bank loaders, this module never creates or updates canonical accounts,
transactions, instruments, or balance snapshots.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from penge.household.models import PaymentDetail
from penge.household.schemas import PaymentDetailWrite as HouseholdPaymentDetailWrite
from penge.household.service import lock_household, upsert_payment_detail
from penge.ingest.enablebanking.loader import LoadResult
from penge.ingest.paypal.mapping import payment_detail_from_transaction

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.engine import Engine

    from penge.ingest.enablebanking.client import Client
    from penge.ingest.enablebanking.models import AccountResource


log = logging.getLogger("penge.ingest.paypal.loader")


class PayPalDetailMappingError(ValueError):
    """A source transaction cannot be safely represented as a payment detail."""


def load_account(
    engine: Engine,
    *,
    client: Client,
    account: AccountResource,
    connection_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> LoadResult:
    """Fetch booked PayPal transactions and persist only payment details.

    Enable Banking's client follows continuation keys and returns the complete
    requested page range. The household service owns the detail schema and
    upsert semantics; this function owns one caller-side transaction per account.
    """
    if account.uid is None:
        raise ValueError("PayPal account has no session UID")

    transactions = client.get_account_transactions(
        account.uid,
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
    ).transactions

    mapped: dict[tuple[str, str], HouseholdPaymentDetailWrite] = {}
    for transaction in transactions:
        try:
            mapped_detail = payment_detail_from_transaction(
                transaction,
                account=account,
                connection_id=connection_id,
            )
            detail = HouseholdPaymentDetailWrite.model_validate(mapped_detail)
        except ValidationError as exc:
            raise PayPalDetailMappingError(
                "PayPal transaction fields exceed the supported detail contract"
            ) from exc
        except ValueError as exc:
            raise PayPalDetailMappingError(str(exc)) from exc
        mapped[(detail.source_account_id, detail.external_id)] = detail

    if not mapped:
        return LoadResult(transactions=0, holding_snapshots=0, writes=0, payment_details=0)

    writes = 0
    with Session(engine) as session, session.begin():
        lock_household(session)
        for detail in mapped.values():
            existing = _existing_revision(session, detail)
            saved = upsert_payment_detail(session, detail)
            if existing is None or saved.revision != existing:
                writes += 1

    log.info(
        "PayPal detail load: details=%d changed=%d",
        len(mapped),
        writes,
    )
    return LoadResult(
        transactions=0,
        holding_snapshots=0,
        writes=writes,
        payment_details=len(mapped),
    )


def _existing_revision(session: Session, detail: HouseholdPaymentDetailWrite) -> int | None:
    """Read the pre-upsert revision so repeat syncs trigger no false refresh."""
    return session.scalar(
        select(PaymentDetail.revision).where(
            PaymentDetail.provider == detail.provider,
            PaymentDetail.source_account_id == detail.source_account_id,
            PaymentDetail.external_id == detail.external_id,
        )
    )


__all__ = ["PayPalDetailMappingError", "load_account"]
