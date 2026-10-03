"""PayPal detail-only ingestion through Enable Banking."""

from penge.ingest.paypal.mapping import (
    PayPalDetailPayload,
    PayPalSourceFields,
    payment_detail_from_transaction,
)

__all__ = ["PayPalDetailPayload", "PayPalSourceFields", "payment_detail_from_transaction"]
