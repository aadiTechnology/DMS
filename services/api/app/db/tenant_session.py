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
