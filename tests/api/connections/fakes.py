"""Fake Enable Banking client for connection tests.

Mirrors the subset of :class:`penge.ingest.enablebanking.client.Client`
the connections service uses, returning the real Pydantic models so the
loaders and mappers run unchanged. No HTTP, no signing key. Each method
can be primed to raise :class:`EnableBankingError` to exercise the
debug/error-recording paths.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from penge.ingest.enablebanking.client import EnableBankingError
from penge.ingest.enablebanking.models import (
    Access,
    AccountIdentification,
    AccountResource,
    Amount,
    Aspsp,
    AuthorizeSessionResponse,
    Balance,
    BalancesResponse,
    GetSessionResponse,
    SessionStatus,
    StartAuthorizationResponse,
    Transaction,
    TransactionsResponse,
)

VALID_UNTIL = datetime(2026, 12, 31, tzinfo=UTC)


def _account(uid: str = "uid-1") -> AccountResource:
    return AccountResource(
        uid=uid,
        name="Synthetic Checking",
        product="Girokonto",
        currency="EUR",
        account_id=AccountIdentification(iban="DE89370400440532013000"),
    )


class FakeClient:
    """In-memory stand-in for the Enable Banking client."""

    def __init__(self) -> None:
        self.authorize_error: EnableBankingError | None = None
        self.get_session_error: EnableBankingError | None = None
        self.session_status: SessionStatus = "AUTHORIZED"
        self.session_accounts: list[AccountResource] = [_account()]
        self.aspsp_name: str = "GLS Gemeinschaftsbank"
        self.aspsp_country: str = "DE"
        # When set, get_account_transactions returns two booked entries that
        # share the same entry_reference, to exercise the upsert dedup path.
        self.duplicate_entry_reference: bool = False
        self.authorize_calls: int = 0
        # When set, get_account_transactions raises WRONG_TRANSACTIONS_PERIOD
        # for any date_from older than this many days, mimicking an ASPSP that
        # only serves a limited history on unattended repeat access.
        self.max_history_days: int | None = None
        # Records the date_from (ISO string) of each transactions call so
        # tests can assert which windows were attempted.
        self.transaction_windows: list[str | None] = []

    # -- context manager ------------------------------------------------ #
    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        return None

    # -- AIS surface ---------------------------------------------------- #
    def start_authorization(
        self,
        *,
        aspsp_name: str,
        aspsp_country: str,
        redirect_url: str,
        valid_until: datetime,
        psu_type: str = "personal",
        state: str | None = None,
        balances: bool = True,
        transactions: bool = True,
    ) -> StartAuthorizationResponse:
        self.aspsp_name = aspsp_name
        self.aspsp_country = aspsp_country
        return StartAuthorizationResponse(
            url=f"https://auth.example/start?state={state}",
            authorization_id="auth-123",
        )

    def authorize_session(self, code: str) -> AuthorizeSessionResponse:
        self.authorize_calls += 1
        if self.authorize_error is not None:
            raise self.authorize_error
        return AuthorizeSessionResponse(
            session_id="sess-123",
            accounts=self.session_accounts,
            aspsp=Aspsp(name=self.aspsp_name, country=self.aspsp_country),
            psu_type="personal",
            access=Access(valid_until=VALID_UNTIL),
        )

    def get_session(self, session_id: str) -> GetSessionResponse:
        _ = session_id
        if self.get_session_error is not None:
            raise self.get_session_error
        return GetSessionResponse(
            status=self.session_status,
            accounts=[a.uid for a in self.session_accounts if a.uid],
            accounts_data=self.session_accounts,
            aspsp=Aspsp(name=self.aspsp_name, country=self.aspsp_country),
            psu_type="personal",
            access=Access(valid_until=VALID_UNTIL),
            created=datetime.now(UTC) - timedelta(days=1),
            authorized=datetime.now(UTC) - timedelta(days=1),
        )

    def get_account_transactions(
        self,
        account_uid: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        transaction_status: str = "BOOK",
        strategy: str | None = None,
    ) -> TransactionsResponse:
        self.transaction_windows.append(date_from)
        if self.max_history_days is not None and date_from is not None:
            oldest_allowed = date.today() - timedelta(days=self.max_history_days)
            if date.fromisoformat(date_from) < oldest_allowed:
                raise EnableBankingError(
                    400,
                    {
                        "error": "WRONG_TRANSACTIONS_PERIOD",
                        "message": "Wrong transactions period requested",
                    },
                )
        txns = [
            Transaction(
                entry_reference=f"{account_uid}-tx-1",
                transaction_amount=Amount(amount=Decimal("12.34"), currency="EUR"),
                credit_debit_indicator="DBIT",
                status="BOOK",
                booking_date=date(2026, 1, 2),
                value_date=date(2026, 1, 2),
                remittance_information=["synthetic"],
            )
        ]
        if self.duplicate_entry_reference:
            # Same entry_reference, different amount: some ASPSPs do this
            # within a single page. The loader must collapse them instead of
            # crashing with ON CONFLICT DO UPDATE CardinalityViolation.
            txns.append(
                Transaction(
                    entry_reference=f"{account_uid}-tx-1",
                    transaction_amount=Amount(amount=Decimal("56.78"), currency="EUR"),
                    credit_debit_indicator="DBIT",
                    status="BOOK",
                    booking_date=date(2026, 1, 3),
                    value_date=date(2026, 1, 3),
                    remittance_information=["synthetic-dup"],
                )
            )
        return TransactionsResponse(transactions=txns)

    def get_account_balances(self, account_uid: str) -> BalancesResponse:
        return BalancesResponse(
            balances=[
                Balance(
                    name="closing",
                    balance_amount=Amount(amount=Decimal("100.00"), currency="EUR"),
                    balance_type="CLBD",
                    reference_date=date(2026, 1, 2),
                )
            ]
        )


def eb_error(status_code: int, code: str, message: str) -> EnableBankingError:
    """Build an Enable Banking error with the production body shape."""
    return EnableBankingError(
        status_code,
        {"code": status_code, "message": message, "error": code, "detail": None},
    )
