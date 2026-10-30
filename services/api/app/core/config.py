from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "dev-only-insecure-secret-do-not-use-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENVIRONMENT: str = "development"
    DATABASE_URL: str = "postgresql+psycopg://dms:dms_dev@localhost:15432/dms"
    SECRET_KEY: str = DEV_SECRET
    # PRD STO-001: 100 MB default, tenant-configurable within plan limits.
    DMS_MAX_UPLOAD_BYTES: int = Field(default=100 * 1024 * 1024, gt=0)
    # Short-lived download URLs (PRD STO-008); ADR-0001 sets 5 minutes.
    DMS_DOWNLOAD_URL_TTL_SECONDS: int = Field(default=300, ge=30, le=900)
    # Authentication (PRD section 15.1)
    ACCESS_TOKEN_TTL_MINUTES: int = Field(default=15, ge=1, le=60)
    REFRESH_TOKEN_TTL_DAYS: int = Field(default=14, ge=1, le=90)
    LOGIN_MAX_FAILURES: int = Field(default=5, ge=3, le=20)
    LOGIN_LOCKOUT_MINUTES: int = Field(default=15, ge=1, le=1440)
    AUTH_RATE_LIMIT_PER_MINUTE: int = Field(default=30, ge=1)

    @model_validator(mode="after")
    def _production_needs_real_secret(self):
        if self.ENVIRONMENT == "production" and (
            self.SECRET_KEY == DEV_SECRET or len(self.SECRET_KEY) < 32
        ):
            raise ValueError("SECRET_KEY must be set to a unique value of 32+ characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
