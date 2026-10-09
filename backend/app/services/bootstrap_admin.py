"""One-time first-administrator bootstrap (Phase 10 §6).

Usage (run from the ``backend`` directory, or with PYTHONPATH set):

    python -m app.services.bootstrap_admin --username alice

The password is read from ``BOOTSTRAP_ADMIN_PASSWORD`` or, interactively,
prompted with hidden input.  Safety rails:

* refuses to run when an active ADMIN already exists (one-time use);
* refuses to run in production with a development/default JWT secret;
* enforces the password policy (≥8 chars, not the username, not a common
  password) and suggests generating one when none is supplied;
* never prints or logs the password.

Existing credentials are *not* modified; use the ADMIN user-management API
(``POST /api/users/{id}/reset-password``) for later resets.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import uuid
from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password, validate_password
from app.models.entities import User
from fastapi import HTTPException


def bootstrap(username: str, password: str, email: str = "") -> User:
    if settings.IS_PRODUCTION and settings.JWT_SECRET.startswith("dev-"):
        raise SystemExit("Refusing to bootstrap while JWT_SECRET is a development default.")

    normalized = username.strip().lower()
    if not normalized or len(normalized) < 3:
        raise SystemExit("Username must be at least 3 characters")
    try:
        validate_password(password, normalized)
    except HTTPException as exc:  # CLI-friendly message (§6)
        raise SystemExit(str(exc.detail))

    with SessionLocal() as db:
        if db.query(User).filter(User.role == "ADMIN", User.is_active.is_(True)).count() > 0:
            raise SystemExit(
                "An active administrator already exists — bootstrap is one-time. "
                "Use the admin API to create additional accounts."
            )
        if db.query(User).filter(User.username == normalized).first():
            raise SystemExit("Username already exists")

        user = User(
            id=f"u_{uuid.uuid4().hex[:10]}",
            username=normalized,
            email=(email.strip().lower() or f"{normalized}@twinsphere.local"),
            password_hash=hash_password(password),
            role="ADMIN",
            password_changed_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        from app.core.audit import audit

        audit(db, "admin.bootstrap", actor=normalized,
              detail="First administrator created via bootstrap CLI", user_id=user.id)
        return user


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create the first TwinSphere administrator")
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", default="")
    args = parser.parse_args(argv)

    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
    if not password:
        if not sys.stdin.isatty():
            print("Set BOOTSTRAP_ADMIN_PASSWORD to bootstrap without a TTY.", file=sys.stderr)
            return 2
        password = getpass.getpass("New administrator password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords do not match.", file=sys.stderr)
            return 2

    try:
        user = bootstrap(args.username, password, args.email)
    except SystemExit as exc:
        if str(exc):
            print(str(exc), file=sys.stderr)
        return 1
    print(f"Created administrator '{user.username}' ({user.id}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
