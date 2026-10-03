"""Synthetic connected browser journeys, separate from the June report goldens."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from penge.api.merchant_reference.store import promote_snapshot
from penge.household import models as m
from penge.household import schemas as s
from penge.household import service
from penge.ingest.merchant_reference.nsi import NsiRelease, NsiSnapshot, PublicMerchantReference

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


def seed_browser_journeys(engine: Engine, account_id: uuid.UUID) -> None:
    """Seed independent device scenarios with explicit synthetic identities."""
    with Session(engine) as session:
        for device in ("desktop", "mobile"):
            label = f"Synthetic browser {device}"
            category = service.save_category(
                session,
                s.CategoryWrite(expected_revision=0, name=f"{label} essentials", kind="expense"),
            )
            service.save_category(
                session,
                s.CategoryWrite(expected_revision=0, name=f"{label} extras", kind="expense"),
            )
            merchant = service.save_merchant(
                session,
                s.MerchantWrite(
                    expected_revision=0,
                    name=f"{label} merchant",
                    identity_kind="stable",
                    confirmed=True,
                ),
            )
            service.save_alias(
                session,
                s.AliasWrite(
                    expected_revision=0,
                    merchant_id=merchant.id,
                    provider="gls",
                    label=merchant.name,
                    confirmed=True,
                ),
            )
            for key, amount in (
                ("evidence", "-10.00"),
                ("history", "-12.00"),
                ("bulk one", "-20.00"),
                ("bulk two", "-30.00"),
                ("paypal", "-42.00"),
            ):
                transaction_id = uuid.uuid5(uuid.NAMESPACE_URL, f"penge-browser/{device}/{key}")
                session.add(
                    m.SourceTransaction(
                        id=transaction_id,
                        account_id=account_id,
                        ts=datetime(2026, 7, 10, 12, tzinfo=UTC),
                        amount=Decimal(amount),
                        kind="withdrawal",
                        counterparty=merchant.name if key in ("evidence", "history") else label,
                        description=f"{label} {key}",
                    )
                )
                session.flush()
                if key == "evidence":
                    service.save_classification(
                        session,
                        transaction_id,
                        s.ClassificationWrite(
                            expected_revision=0,
                            treatment="expense",
                            merchant_id=merchant.id,
                            identity_confirmed=True,
                            allocations=[s.Split(category_id=category.id, amount=Decimal(amount))],
                            explanation="Synthetic protected evidence for browser history journey",
                        ),
                    )
            for item, amount in (("a", "-20.00"), ("b", "-22.00")):
                service.upsert_payment_detail(
                    session,
                    s.PaymentDetailWrite(
                        provider="paypal",
                        source_account_id=f"DE:synthetic-browser-{device}",
                        external_id=f"synthetic-browser-{device}-{item}",
                        ts=datetime(2026, 7, 9, 12, tzinfo=UTC),
                        amount=Decimal(amount),
                        currency="EUR",
                        merchant_name=f"{label} detail {item}",
                        reference=f"synthetic-browser-{device}-{item}",
                        event_kind="unknown",
                    ),
                )
        session.commit()

    version = "8.0.20260701"
    now = datetime.now(UTC)
    source_url = f"https://cdn.jsdelivr.net/npm/name-suggestion-index@{version}/dist/json/nsi.json"
    records = tuple(
        PublicMerchantReference(
            source_entity_id=f"synthetic-browser-{device}",
            label=f"Synthetic browser {device} public",
            aliases=(f"Synthetic browser {device} public",),
            category_path="brands/shop/supermarket",
            source_version=version,
            source_revision_at=now,
            source_url=source_url,
        )
        for device in ("desktop", "mobile")
    )
    promote_snapshot(
        engine,
        NsiSnapshot(
            source_version=version,
            source_generated_at=now,
            retrieved_at=now,
            source_url=source_url,
            sha256=hashlib.sha256(b"synthetic-browser-public-catalog").hexdigest(),
            record_count=len(records),
            records=records,
        ),
        NsiRelease(
            version=version,
            license="BSD-3-Clause",
            integrity="sha512-c3ludGhldGlj",
            tarball_url=(
                "https://registry.npmjs.org/name-suggestion-index/-/"
                f"name-suggestion-index-{version}.tgz"
            ),
        ),
    )
