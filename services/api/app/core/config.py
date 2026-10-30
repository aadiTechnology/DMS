from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "dev-only-insecure-secret-do-not-use-in-production"
# Buckets of the existing ERP: the DMS must never share them (ADR-0001).
FORBIDDEN_BUCKETS = frozenset({"attachmentserp-b2", "aaditech-erp-test-v2"})


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
    CATEGORY_MAX_DEPTH: int = Field(default=8, ge=1, le=20)
    # Uploads (PRD section 8.1)
    UPLOAD_RESERVATION_MINUTES: int = Field(default=60, ge=5, le=1440)
    UPLOAD_TMP_DIR: str = ""  # empty = the system temp folder
    # Search and text extraction (PRD section 9)
    SEARCH_RATE_LIMIT_PER_MINUTE: int = Field(default=120, ge=1)
    EXTRACT_TIMEOUT_SECONDS: int = Field(default=60, ge=5, le=600)
    EXTRACT_MAX_CHARS: int = Field(default=2_000_000, ge=1000, le=20_000_000)
    EXTRACT_MAX_ATTEMPTS: int = Field(default=3, ge=1, le=10)
    # Malware scanning. `dev` is a stand-in for development only; production needs ClamAV.
    SCANNER_BACKEND: Literal["dev", "clamav"] = "dev"
    CLAMD_HOST: str = "localhost"
    CLAMD_PORT: int = Field(default=3310, ge=1, le=65535)
    CLAMD_TIMEOUT_SECONDS: int = Field(default=120, ge=5, le=900)
    INVITE_TTL_HOURS: int = Field(default=168, ge=1, le=720)
    RESET_TTL_MINUTES: int = Field(default=60, ge=5, le=1440)
    # Email. `console` (development only) logs messages; `smtp` works with any provider.
    APP_BASE_URL: str = "http://localhost:5173"
    EMAIL_BACKEND: Literal["console", "outbox", "smtp"] = "console"
    EMAIL_FROM: str = "no-reply@dms.local"
    EMAIL_SMTP_HOST: str = ""
    EMAIL_SMTP_PORT: int = 587
    EMAIL_SMTP_USER: str = ""
    EMAIL_SMTP_PASSWORD: str = ""
    # SSO: public OAuth client ids (not secrets). Empty disables that provider.
    SSO_GOOGLE_CLIENT_ID: str = ""
    SSO_MICROSOFT_CLIENT_ID: str = ""
    # Encrypts TOTP secrets at rest. Falls back to a key derived from SECRET_KEY.
    MFA_ENCRYPTION_KEY: str = ""
    # Object storage (ADR-0001). `local` is for development/tests only.
    STORAGE_PROVIDER: Literal["local", "backblaze"] = "local"
    STORAGE_LOCAL_DIR: str = ".storage"
    API_BASE_URL: str = "http://localhost:8000"
    DMS_B2_KEY_ID: str = ""
    DMS_B2_APP_KEY: SecretStr = SecretStr("")
    DMS_B2_BUCKET_NAME: str = ""

    @model_validator(mode="after")
    def _production_needs_real_secret(self):
        if self.ENVIRONMENT == "production" and (
            self.SECRET_KEY == DEV_SECRET or len(self.SECRET_KEY) < 32
        ):
            raise ValueError("SECRET_KEY must be set to a unique value of 32+ characters")
        if self.ENVIRONMENT == "production" and self.EMAIL_BACKEND != "smtp":
            raise ValueError("EMAIL_BACKEND must be 'smtp' in production")
        if self.ENVIRONMENT == "production" and self.STORAGE_PROVIDER != "backblaze":
            raise ValueError("STORAGE_PROVIDER must be 'backblaze' in production")
        if self.ENVIRONMENT == "production" and self.SCANNER_BACKEND != "clamav":
            raise ValueError("SCANNER_BACKEND must be 'clamav' in production")
        if self.STORAGE_PROVIDER == "backblaze":
            missing = [
                name
                for name, value in (
                    ("DMS_B2_KEY_ID", self.DMS_B2_KEY_ID),
                    ("DMS_B2_APP_KEY", self.DMS_B2_APP_KEY.get_secret_value()),
                    ("DMS_B2_BUCKET_NAME", self.DMS_B2_BUCKET_NAME),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"Backblaze storage needs: {', '.join(missing)}")
            if self.DMS_B2_BUCKET_NAME in FORBIDDEN_BUCKETS:
                raise ValueError("DMS_B2_BUCKET_NAME must be a DMS-only bucket, not an ERP bucket")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
