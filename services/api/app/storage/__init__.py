from functools import lru_cache

from app.core.config import Settings, get_settings
from app.storage.base import StorageConfigError, StorageProvider


def build_storage(settings: Settings) -> StorageProvider:
    if settings.STORAGE_PROVIDER == "local":
        from app.storage.local import LocalStorage

        return LocalStorage(settings)
    if settings.STORAGE_PROVIDER == "backblaze":
        from app.storage.backblaze import BackblazeStorage

        return BackblazeStorage(settings)
    raise StorageConfigError("unknown storage provider")


@lru_cache
def get_storage() -> StorageProvider:
    """One provider (and one SDK client / connection pool) per process."""
    return build_storage(get_settings())


def dev_storage_enabled(settings: Settings) -> bool:
    return settings.STORAGE_PROVIDER == "local" and settings.ENVIRONMENT != "production"
