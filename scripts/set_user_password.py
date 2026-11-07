import argparse
from getpass import getpass

from sqlalchemy import func, select

from app.auth import hash_password
from app.database import SessionLocal
from app.models import User


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set or reset one active LedgerForge user password."
    )
    parser.add_argument("--username", required=True)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Allow replacing an existing password hash.",
    )
    args = parser.parse_args()

    password = getpass("New password (minimum 12 characters): ")
    confirmation = getpass("Confirm new password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")
    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters.")

    with SessionLocal.begin() as db:
        user = db.scalar(
            select(User).where(
                func.lower(User.username)
                == args.username.strip().lower()
            )
        )
        if user is None:
            raise SystemExit("No user matches that username.")
        if user.is_active != "Y":
            raise SystemExit("Inactive users cannot be provisioned.")
        if user.password_hash and not args.reset:
            raise SystemExit(
                "The user already has a password; rerun with --reset to replace it."
            )
        user.password_hash = hash_password(password)

    print(f"Password configured for {args.username.strip()}.")


if __name__ == "__main__":
    main()
