"""Utility script to safely rotate an admin or user password in the database.

Usage:
    python -m scripts.rotate_admin_password --username admin
"""
import argparse
import getpass
import sys

from sqlalchemy import select

from app.auth import hash_password
from app.db import SessionLocal
from app.models import User


def rotate_password(username: str, new_password: str) -> bool:
    if len(new_password) < 12:
        print("Error: Password must be at least 12 characters long.", file=sys.stderr)
        return False

    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.username == username))
        if not user:
            print(f"Error: User '{username}' not found in database.", file=sys.stderr)
            return False

        user.password_hash = hash_password(new_password)
        session.commit()
        print(f"Successfully updated password hash for user '{username}'.")
        return True


def main():
    parser = argparse.ArgumentParser(description="Rotate user password safely.")
    parser.add_argument("--username", default="admin", help="Username to update (default: admin)")
    args = parser.parse_args()

    password = getpass.getpass(prompt=f"Enter new password for '{args.username}': ")
    confirm = getpass.getpass(prompt="Confirm new password: ")
    if password != confirm:
        print("Error: Passwords do not match.", file=sys.stderr)
        sys.exit(1)

    success = rotate_password(args.username, password)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
