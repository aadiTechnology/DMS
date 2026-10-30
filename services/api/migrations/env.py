from alembic import context
from sqlalchemy import create_engine

from app.core.config import get_settings
from app.db import models  # noqa: F401  (register tables)
from app.db.base import Base

target_metadata = Base.metadata


def _url() -> str:
    # Tests and tooling may inject the URL; otherwise use application settings.
    return context.config.attributes.get("url") or get_settings().DATABASE_URL


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
