"""Manage GrootOps Legal lawyer accounts. Passwords are typed at a hidden prompt, never passed as arguments.

    python -m groot_ops.legal.manage add-user --email ada@firm.ng --name "Ada Obi" --firm "Pilot Chambers"
    python -m groot_ops.legal.manage set-password --email ada@firm.ng
    python -m groot_ops.legal.manage list-users
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from groot_ops.legal.store import LegalStore


def ask_password() -> str:
    first = getpass.getpass("Password (at least 10 characters): ")
    if first != getpass.getpass("Type it again: "):
        sys.exit("The passwords don't match.")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GrootOps Legal accounts")
    parser.add_argument("--db", default=os.environ.get("LEGAL_DB", "legal.sqlite3"))
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add-user")
    add.add_argument("--email", required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--firm", default="")
    reset = sub.add_parser("set-password")
    reset.add_argument("--email", required=True)
    sub.add_parser("list-users")
    args = parser.parse_args(argv)

    store = LegalStore(args.db)
    try:
        if args.command == "add-user":
            store.add_user(args.email, args.name, ask_password(), args.firm)
            print(f"Added {args.email}.")
        elif args.command == "set-password":
            print("Password changed." if store.set_password(args.email, ask_password()) else "No account with that email.")
        else:
            for user in store.users():
                print(f"{user['email']}\t{user['name']}\t{user['firm']}")
    except ValueError as error:
        sys.exit(str(error))
    return 0


if __name__ == "__main__":
    sys.exit(main())
