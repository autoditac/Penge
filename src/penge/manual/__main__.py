"""Typer CLI for the manual-entry workflow.

Subcommands::

    penge-manual add-balance --entity Rouven --account "DKB Tagesgeld" \\
        --currency EUR --balance 12345.67

    penge-manual mark-property --entity Rouven \\
        --account "Nederbyvej 36" --property "Nederbyvej 36 (DK)" \\
        --currency DKK --valuation 4500000

Reads ``DATABASE_URL`` (or assembled ``POSTGRES_*``) just like Alembic.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Annotated

import typer

from .entries import BalanceEntry, PropertyEntry
from .service import record_cash_balance, record_property_value

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

log = logging.getLogger("penge.manual")

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Record manually-tracked cash balances and real-estate valuations.",
)


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    user = os.environ.get("POSTGRES_USER", "penge")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "penge")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


def _engine() -> Engine:
    # Lazy import so ``--help`` works without DB drivers installed.
    from sqlalchemy import create_engine

    return create_engine(_database_url())


def _parse_decimal(value: str, field: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise typer.BadParameter(f"{field} is not a valid decimal: {value!r}") from exc


def _parse_as_of(value: str | None) -> date:
    if value is None:
        return date.today()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise typer.BadParameter(f"--as-of must be YYYY-MM-DD, got {value!r}") from exc


@app.callback()
def _root(
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Enable debug logging.")] = False,
) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@app.command("add-balance")
def add_balance(
    entity: Annotated[str, typer.Option("--entity", help="Account owner name (e.g. 'Rouven').")],
    account: Annotated[str, typer.Option("--account", help="Human account name.")],
    currency: Annotated[str, typer.Option("--currency", help="ISO-4217 3-letter code.")],
    balance: Annotated[str, typer.Option("--balance", help="Balance as decimal, e.g. 1234.56.")],
    as_of: Annotated[
        str | None,
        typer.Option("--as-of", help="Snapshot date YYYY-MM-DD (default: today)."),
    ] = None,
    note: Annotated[str | None, typer.Option("--note", help="Optional free-form note.")] = None,
) -> None:
    """Record a cash-account balance snapshot."""
    try:
        entry = BalanceEntry(
            entity=entity,
            account_name=account,
            currency=currency,
            as_of=_parse_as_of(as_of),
            balance=_parse_decimal(balance, "balance"),
            note=note,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    record_cash_balance(_engine(), entry)
    typer.echo(f"recorded balance: {entry.account_name} {entry.balance} {entry.currency}")


@app.command("mark-property")
def mark_property(
    entity: Annotated[str, typer.Option("--entity", help="Account owner name.")],
    account: Annotated[str, typer.Option("--account", help="Human account name.")],
    property_: Annotated[str, typer.Option("--property", help="Property label.")],
    currency: Annotated[str, typer.Option("--currency", help="ISO-4217 3-letter code.")],
    valuation: Annotated[str, typer.Option("--valuation", help="Valuation as decimal.")],
    as_of: Annotated[
        str | None,
        typer.Option("--as-of", help="Snapshot date YYYY-MM-DD (default: today)."),
    ] = None,
    note: Annotated[str | None, typer.Option("--note", help="Optional free-form note.")] = None,
) -> None:
    """Record a real-estate valuation snapshot."""
    try:
        entry = PropertyEntry(
            entity=entity,
            account_name=account,
            property_name=property_,
            currency=currency,
            as_of=_parse_as_of(as_of),
            valuation=_parse_decimal(valuation, "valuation"),
            note=note,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    record_property_value(_engine(), entry)
    typer.echo(f"recorded property: {entry.property_name} {entry.valuation} {entry.currency}")


def main(argv: list[str] | None = None) -> int:
    # Provide a Click-style entry compatible with __main__:app and tests.
    try:
        app(args=argv, standalone_mode=False)
    except typer.Exit as exc:  # pragma: no cover - CLI plumbing
        return int(exc.exit_code)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
