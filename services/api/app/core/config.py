from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENVIRONMENT: str = "development"
    DATABASE_URL: str = "postgresql+psycopg://dms:dms_dev@localhost:15432/dms"
    # PRD STO-001: 100 MB default, tenant-configurable within plan limits.
    DMS_MAX_UPLOAD_BYTES: int = Field(default=100 * 1024 * 1024, gt=0)
    # Short-lived download URLs (PRD STO-008); ADR-0001 sets 5 minutes.
    DMS_DOWNLOAD_URL_TTL_SECONDS: int = Field(default=300, ge=30, le=900)


def get_settings() -> Settings:
    return Settings()
