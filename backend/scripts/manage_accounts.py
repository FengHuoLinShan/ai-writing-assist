#!/usr/bin/env python3
"""Narrow operational CLI for account metadata and lifecycle actions."""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from core.database import get_manager  # noqa: E402
from modules.account.email_sender import send_login_code  # noqa: E402
from modules.account.models import Account, AccountIdentity  # noqa: E402
from modules.account.services import normalize_email, service  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status")
    status.add_argument("account", help="account UUID or support code")
    for name in ("ban", "unban"):
        command = commands.add_parser(name)
        command.add_argument("account_id", type=uuid.UUID)
    claim = commands.add_parser("claim-legacy")
    claim.add_argument("--email", required=True)
    purge = commands.add_parser("purge-due")
    purge.add_argument("--execute", action="store_true")
    smoke = commands.add_parser("smtp-smoke")
    smoke.add_argument("--to", required=True)
    return parser


async def _find_account(db, value: str) -> Account | None:
    try:
        account_id = uuid.UUID(value)
    except ValueError:
        account_id = None
    statement = select(Account)
    if account_id is not None:
        statement = statement.where(Account.id == account_id)
    else:
        statement = statement.where(Account.support_code == value)
    return (await db.execute(statement)).scalar_one_or_none()


async def _run(args: argparse.Namespace) -> int:
    manager = get_manager()
    if args.command == "smtp-smoke":
        await send_login_code(normalize_email(args.to), "123456")
        print("SMTP smoke message accepted by server")
        await manager.close()
        return 0
    async with manager.session() as db:
        if args.command == "status":
            account = await _find_account(db, args.account)
            if account is None:
                print("account not found", file=sys.stderr)
                return 1
            identity = (
                await db.execute(
                    select(AccountIdentity.provider).where(
                        AccountIdentity.account_id == account.id
                    )
                )
            ).scalar_one_or_none()
            print(
                f"id={account.id} support_code={account.support_code} "
                f"status={account.status} identity={identity or 'unclaimed'} "
                f"purge_after={account.purge_after or '-'}"
            )
        elif args.command == "claim-legacy":
            account = await service.claim_legacy(db, args.email)
            print(
                f"legacy account claimed id={account.id} "
                f"support_code={account.support_code}"
            )
        elif args.command in {"ban", "unban"}:
            account = await service.set_banned(
                db,
                args.account_id,
                banned=args.command == "ban",
            )
            print(
                f"id={account.id} support_code={account.support_code} "
                f"status={account.status}"
            )
        elif args.command == "purge-due":
            ids = await service.purge_due(db, execute=args.execute)
            print(f"due={len(ids)} executed={bool(args.execute)}")
    await manager.close()
    return 0


def main() -> int:
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
