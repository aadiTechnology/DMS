"""Operator command to manage platform administrators (people who may publish UI templates).

    uv run python -m app.platform_admin list
    uv run python -m app.platform_admin grant person@example.com
    uv run python -m app.platform_admin revoke person@example.com

Runs on the owner database connection. There is no web or API way to grant this role. The last
active platform administrator cannot be revoked.
"""

import sys
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import PlatformAdmin, User
from app.db.session import get_engine


def _user(db: Session, email: str) -> User:
    user = db.scalars(select(User).where(func.lower(User.email) == email.strip().lower())).first()
    if user is None:
        raise LookupError("No user account has that email address")
    return user


def grant(db: Session, email: str) -> str:
    user = _user(db, email)
    row = db.get(PlatformAdmin, user.id)
    if row is None:
        db.add(PlatformAdmin(user_id=user.id, granted_by="command"))
        return "granted"
    if row.revoked_at is None:
        return "already an administrator"
    row.revoked_at = None
    return "granted again"


def revoke(db: Session, email: str) -> str:
    user = _user(db, email)
    row = db.get(PlatformAdmin, user.id)
    if row is None or row.revoked_at is not None:
        return "not an administrator"
    active = db.scalar(
        select(func.count()).select_from(PlatformAdmin).where(PlatformAdmin.revoked_at.is_(None))
    )
    if active <= 1:
        raise ValueError("Refusing to revoke the last platform administrator")
    row.revoked_at = datetime.now(UTC)
    return "revoked"


def listing(db: Session) -> list[str]:
    rows = db.execute(
        select(User.email, PlatformAdmin.revoked_at)
        .join(User, User.id == PlatformAdmin.user_id)
        .order_by(User.email)
    ).all()
    return [f"{email}{' (revoked)' if revoked else ''}" for email, revoked in rows]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if (
        not args
        or args[0] not in ("list", "grant", "revoke")
        or (args[0] != "list" and len(args) != 2)
    ):
        print(
            "usage: python -m app.platform_admin list | grant <email> | revoke <email>",
            file=sys.stderr,
        )
        return 2
    try:
        with Session(get_engine()) as db, db.begin():
            if args[0] == "list":
                print("\n".join(listing(db)) or "(no platform administrators)")
            else:
                print((grant if args[0] == "grant" else revoke)(db, args[1]))
    except (LookupError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
