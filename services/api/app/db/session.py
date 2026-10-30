from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """One pooled engine per process (reuse connections)."""
    return create_engine(get_settings().DATABASE_URL, pool_pre_ping=True)


def get_session() -> Session:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)()
