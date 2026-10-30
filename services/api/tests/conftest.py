import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ADMIN_URL = os.environ.get(
    "DMS_TEST_ADMIN_URL", "postgresql+psycopg://dms:dms_dev@localhost:15432/postgres"
)


def alembic_config(url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.attributes["url"] = url
    return cfg


@pytest.fixture
def empty_db_url():
    """A fresh, empty database per test; dropped afterwards. Never touches the dev database."""
    name = f"dms_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
    try:
        yield url
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def migrated_engine(empty_db_url):
    command.upgrade(alembic_config(empty_db_url), "head")
    engine = create_engine(empty_db_url)
    yield engine
    engine.dispose()
