import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import app


def test_health_ok():
    r = TestClient(app).get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_defaults_match_prd():
    s = Settings(_env_file=None)
    assert s.DMS_MAX_UPLOAD_BYTES == 104857600
    assert s.DMS_DOWNLOAD_URL_TTL_SECONDS == 300


def test_download_ttl_upper_bound_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, DMS_DOWNLOAD_URL_TTL_SECONDS=3600)
