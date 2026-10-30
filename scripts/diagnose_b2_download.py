"""Diagnostic for the live download-link 401: tries URL variants and prints only HTTP status and
Backblaze's error code. Uses the same environment variables as the live test. Never prints keys."""

import hashlib
import json
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from app.core.config import Settings
from app.storage import keys as k
from app.storage.backblaze import BackblazeStorage


def fetch(url, headers=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=30) as r:
            return r.status, "ok"
    except urllib.error.HTTPError as exc:
        try:
            code = json.loads(exc.read()).get("code", "?")
        except Exception:
            code = "?"
        return exc.code, code


storage = BackblazeStorage(Settings())
key = k.build_object_key(uuid.uuid4(), uuid.uuid4(), 1, uuid.uuid4(), "diag.txt")
data = b"diagnostic"
with tempfile.NamedTemporaryFile(delete=False) as h:
    h.write(data)
path = Path(h.name)
try:
    storage.put_file(
        key, path, content_type="text/plain",
        sha1=hashlib.sha1(data).hexdigest(), sha256=hashlib.sha256(data).hexdigest(),
    )
    bucket = storage._connect()
    token = bucket.get_download_authorization(file_name_prefix=key, valid_duration_in_seconds=120)
    base = bucket.get_download_url(key)
    disp = 'attachment; filename="report.txt"'
    cases = {
        "A token in query, no overrides": (f"{base}?{urlencode({'Authorization': token})}", None),
        "B token in query + b2ContentDisposition": (f"{base}?{urlencode({'Authorization': token, 'b2ContentDisposition': disp})}", None),
        "C token in query + b2CacheControl": (f"{base}?{urlencode({'Authorization': token, 'b2CacheControl': 'private, no-store'})}", None),
        "D token in query + both (current)": (storage.create_download_url(key, ttl_seconds=120, filename="report.txt"), None),
        "E token in header, no overrides": (base, {"Authorization": token}),
        "F token in header + both overrides": (f"{base}?{urlencode({'b2ContentDisposition': disp, 'b2CacheControl': 'private, no-store'})}", {"Authorization": token}),
        "G no token": (base, None),
    }
    for name, (url, headers) in cases.items():
        print(f"{name}: HTTP {fetch(url, headers)}")
finally:
    path.unlink(missing_ok=True)
    BackblazeStorage(Settings()).delete(key)
