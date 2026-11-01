"""Operator command for the first deployment: create an organization with its first administrator,
and issue a one-time "set your password" link without sending email (useful before SMTP exists).

    python -m app.provision create-org --name "Acme Ltd" --admin-email a@acme.com --admin-name "A Person" [--slug acme]
    python -m app.provision link a@acme.com

Runs on the owner database connection (inside the api container). There is no web or API way to
create an organization. The link is printed once to this terminal and is valid for 48 hours; it is
never written to the application log.
"""

import argparse
import sys
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import EmployeeProfile, TenantMembership, User
from app.db.session import get_engine
from app.services import onboarding
from app.services.tenants import provision_tenant

LINK_HOURS = 48


def _link(db: Session, user: User) -> str:
    raw = onboarding._issue_token(
        db, "password_reset", user.id, None, None, timedelta(hours=LINK_HOURS)
    )
    return f"{get_settings().APP_BASE_URL.rstrip('/')}/reset-password?token={raw}"


def _find(db: Session, email: str) -> User | None:
    return db.scalars(select(User).where(func.lower(User.email) == email.strip().lower())).first()


def create_org(db: Session, name: str, admin_email: str, admin_name: str, slug: str | None) -> str:
    email = admin_email.strip().lower()
    if "@" not in email or not name.strip() or not admin_name.strip():
        raise ValueError("Give an organization name, an administrator name and a valid email")
    user = _find(db, email)
    if user is None:
        user = User(email=email, password_hash=None)
        db.add(user)
        db.flush()
    tenant_id = provision_tenant(db, name.strip(), user.id, slug=slug)
    membership = db.scalars(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id, TenantMembership.user_id == user.id
        )
    ).one()
    db.add(
        EmployeeProfile(
            tenant_id=tenant_id,
            membership_id=membership.id,
            full_name=admin_name.strip(),
            work_email=email,
        )
    )
    db.flush()
    return _link(db, user)


def make_link(db: Session, email: str) -> str:
    user = _find(db, email)
    if user is None or user.status != "active":
        raise LookupError("No active user account has that email address")
    return _link(db, user)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.provision")
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("create-org")
    c.add_argument("--name", required=True)
    c.add_argument("--admin-email", required=True)
    c.add_argument("--admin-name", required=True)
    c.add_argument("--slug")
    sub.add_parser("link").add_argument("email")
    args = parser.parse_args(argv)
    try:
        with Session(get_engine()) as db, db.begin():
            if args.command == "create-org":
                link = create_org(db, args.name, args.admin_email, args.admin_name, args.slug)
                print(
                    f"Organization created. Give this link to {args.admin_email} (valid {LINK_HOURS} hours):"
                )
            else:
                link = make_link(db, args.email)
                print(f"One-time link for {args.email} (valid {LINK_HOURS} hours):")
            print(link)
    except (ValueError, LookupError) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
