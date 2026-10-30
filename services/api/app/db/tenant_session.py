import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.db.rls import APP_ROLE, AUTH_ROLE, TENANT_SETTING
from app.db.session import get_engine


@contextmanager
def tenant_session(tenant_id: uuid.UUID, engine=None) -> Iterator[Session]:
    """One transaction bound to a tenant: runs as dms_app with app.tenant_id set (both LOCAL).

    Commits on success, rolls back on error. The settings vanish when the transaction ends, so
    pooled connections never carry a tenant between requests.
    """
    factory = sessionmaker(bind=engine or get_engine(), expire_on_commit=False)
    with factory() as session, session.begin():
        session.execute(text(f"SET LOCAL ROLE {APP_ROLE}"))
        session.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": TENANT_SETTING, "value": str(tenant_id)},
        )
        yield session


@contextmanager
def auth_session(engine=None) -> Iterator[Session]:
    """Transaction for authentication code only: runs as dms_auth (users, sessions, and
    cross-tenant read of memberships). Never use for tenant request work."""
    factory = sessionmaker(bind=engine or get_engine(), expire_on_commit=False)
    with factory() as session, session.begin():
        session.execute(text(f"SET LOCAL ROLE {AUTH_ROLE}"))
        yield session


_SWITCHABLE = {APP_ROLE, AUTH_ROLE}


@contextmanager
def acting_as(db: Session, role: str, tenant_id: uuid.UUID | None = None) -> Iterator[None]:
    """Temporarily run part of the current transaction as another application role.

    Used by onboarding, which must touch global tables (authentication role) and tenant tables
    (tenant role) atomically. SET ROLE is checked against the connection's login user, so
    switching between the two application roles is permitted. Only dms_app/dms_auth are allowed.
    """
    if role not in _SWITCHABLE:
        raise ValueError("unsupported role")
    previous_role = db.execute(text("SELECT current_user")).scalar()
    previous_tenant = db.execute(
        text("SELECT current_setting(:n, true)"), {"n": TENANT_SETTING}
    ).scalar()
    db.flush()  # pending rows must be written under the role that owns them
    db.execute(text(f"SET LOCAL ROLE {role}"))
    if tenant_id is not None:
        db.execute(
            text("SELECT set_config(:n, :v, true)"), {"n": TENANT_SETTING, "v": str(tenant_id)}
        )
    try:
        yield
        db.flush()
    finally:
        try:
            db.execute(
                text("SELECT set_config(:n, :v, true)"),
                {"n": TENANT_SETTING, "v": previous_tenant or ""},
            )
            db.execute(text(f'SET LOCAL ROLE "{previous_role}"'))
        except Exception:
            # Transaction already aborted; the original error is the one worth reporting.
            logging.getLogger("dms.db").debug("role restore skipped", exc_info=True)
