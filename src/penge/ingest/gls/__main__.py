"""CLI for the GLS Bank connector (issue #14).

Three subcommands map onto the Enable Banking AIS lifecycle:

* ``link``     — print the PSU consent URL for GLS. After consent the
                 PSU is redirected to ``--redirect-url`` with a
                 ``?code=...`` query parameter.
* ``authorize``— exchange that ``code`` for a ``session_id`` and print
                 the list of authorised account UIDs.
* ``sync``     — pull booked transactions and the latest balance for
                 each account in the session and upsert into Postgres.

The session_id is the unit of consent (~180 days for GLS); save it
somewhere and pass via ``--session-id`` or ``GLS_SESSION_ID``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, date, datetime, timedelta

from penge.ingest.enablebanking.client import (
    Client,
    ClientConfig,
    default_consent_until,
)

from .loader import load_account

log = logging.getLogger("penge.ingest.gls")

ASPSP_NAME = "GLS Bank"
ASPSP_COUNTRY = "DE"
DEFAULT_HISTORY_DAYS = 365


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


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="penge-gls",
        description="Load GLS Bank transactions via Enable Banking PSD2 into Postgres.",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    pl = sub.add_parser("link", help="print PSU consent URL for GLS Bank")
    pl.add_argument(
        "--redirect-url",
        required=True,
        help="must match an Allowed redirect URL in the Enable Banking app",
    )
    pl.add_argument(
        "--days",
        type=int,
        default=180,
        help="consent validity in days (default 180; capped by ASPSP)",
    )
    pl.add_argument(
        "--state",
        default=None,
        help="opaque CSRF state echoed back in the redirect (default: random uuid)",
    )

    pa = sub.add_parser("authorize", help="exchange redirect code for a session_id")
    pa.add_argument(
        "--code",
        required=True,
        help="value of the ?code= query parameter from the redirect",
    )

    ps = sub.add_parser("sync", help="pull transactions + balance for all session accounts")
    ps.add_argument(
        "--session-id",
        default=os.environ.get("GLS_SESSION_ID"),
        help="defaults to $GLS_SESSION_ID",
    )
    ps.add_argument(
        "--entity-name",
        default=os.environ.get("GLS_ENTITY_NAME", "Account Holder"),
        help="canonical entity (person) name; defaults to $GLS_ENTITY_NAME",
    )
    ps.add_argument(
        "--days",
        type=int,
        default=DEFAULT_HISTORY_DAYS,
        help=f"days of history to request (default {DEFAULT_HISTORY_DAYS})",
    )
    ps.add_argument(
        "--account-uid",
        action="append",
        help="restrict to one or more account UIDs; repeatable",
    )
    return p


def _cmd_link(args: argparse.Namespace, client: Client) -> int:
    valid_until = default_consent_until(days=args.days)
    resp = client.start_authorization(
        aspsp_name=ASPSP_NAME,
        aspsp_country=ASPSP_COUNTRY,
        redirect_url=args.redirect_url,
        valid_until=valid_until,
        state=args.state,
    )
    print(
        json.dumps(
            {
                "consent_url": resp.url,
                "authorization_id": resp.authorization_id,
                "valid_until": valid_until.isoformat(),
            },
            indent=2,
        )
    )
    sys.stderr.write(
        "\nOpen the consent_url in a browser. After approving, you will be "
        "redirected to:\n"
        f"  {args.redirect_url}?code=<CODE>&state=...\n"
        "Pass the value of <CODE> to:\n"
        "  penge-gls authorize --code <CODE>\n"
    )
    return 0


def _cmd_authorize(args: argparse.Namespace, client: Client) -> int:
    resp = client.authorize_session(args.code)
    payload = {
        "session_id": resp.session_id,
        "valid_until": resp.access.valid_until.isoformat(),
        "accounts": [
            {
                "uid": a.uid,
                "iban": a.account_id.iban if a.account_id else None,
                "name": a.name,
                "currency": a.currency,
                "product": a.product,
            }
            for a in resp.accounts
        ],
    }
    print(json.dumps(payload, indent=2))
    sys.stderr.write(
        f"\nSave the session_id (export GLS_SESSION_ID={resp.session_id}) and run:\n"
        "  penge-gls sync --session-id <SESSION_ID>\n"
    )
    return 0


def _cmd_sync(args: argparse.Namespace, client: Client) -> int:
    if not args.session_id:
        sys.stderr.write("error: --session-id (or $GLS_SESSION_ID) is required\n")
        return 2

    session = client.get_session(args.session_id)
    if session.status != "AUTHORIZED":
        sys.stderr.write(
            f"error: session {args.session_id} status is {session.status} "
            "(re-link required)\n"
        )
        return 2

    # Lazy DB import so --help / link / authorize don't need psycopg.
    from sqlalchemy import create_engine  # noqa: PLC0415

    engine = create_engine(_database_url())
    date_from = (datetime.now(UTC) - timedelta(days=args.days)).date()
    date_to = date.today()

    selected = [
        a for a in session.accounts_data
        if a.uid is not None and (not args.account_uid or a.uid in args.account_uid)
    ]
    if not selected:
        sys.stderr.write("error: no accounts to sync\n")
        return 2

    total_txn = 0
    total_snap = 0
    for acct in selected:
        if acct.uid is None:  # narrow for type-checker; filtered above
            continue
        result = load_account(
            engine,
            client=client,
            account_uid=acct.uid,
            entity_name=args.entity_name,
            account_name=acct.name or acct.product or "GLS account",
            currency=(acct.currency or "EUR").upper(),
            iban=acct.account_id.iban if acct.account_id else None,
            date_from=date_from,
            date_to=date_to,
        )
        total_txn += result.transactions
        total_snap += result.holding_snapshots
        log.info(
            "synced uid=%s txns=%d snapshots=%d",
            acct.uid,
            result.transactions,
            result.holding_snapshots,
        )
    print(
        json.dumps(
            {"transactions": total_txn, "holding_snapshots": total_snap},
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = ClientConfig.from_env()
    with Client(config) as client:
        if args.command == "link":
            return _cmd_link(args, client)
        if args.command == "authorize":
            return _cmd_authorize(args, client)
        if args.command == "sync":
            return _cmd_sync(args, client)
    return 2  # pragma: no cover - argparse enforces required subcommand


if __name__ == "__main__":
    sys.exit(main())
