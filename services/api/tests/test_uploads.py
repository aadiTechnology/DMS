# ruff: noqa: F811
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.db.tenant_session import tenant_session
from app.services import rbac, uploads
from app.services.filetypes import FileRejected
from app.services.scanner import DEV_VIRUS_MARKER, ScanResult
from app.storage.base import StorageError
from app.storage.local import LocalStorage
from tests.test_rbac import auth, env  # noqa: F401  (fixtures)

PDF = b"%PDF-1.7\n" + b"hello world " * 100


@pytest.fixture
def world(env, tmp_path, monkeypatch):
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(get_settings(), "UPLOAD_TMP_DIR", str(tmp_path / "tmp"))
    storage = LocalStorage(Settings(_env_file=None, STORAGE_LOCAL_DIR=str(tmp_path / "store")))
    monkeypatch.setattr("app.api.documents.get_storage", lambda: storage)
    env.storage, env.tmp = storage, tmp_path / "tmp"
    with tenant_session(env.ta, env.engine) as s:
        rbac.assign_role(s, env.ta, env.admin_a, env.mem_emp, env.roles_a["employee"])
    env.admin, env.emp = auth(env, "admin-a@x.test"), auth(env, "emp-a@x.test")
    env.admin_b = auth(env, "admin-b@x.test")

    def post(path, body, h=env.admin):
        r = env.client.post(path, json=body, headers=h)
        assert r.status_code == 201, r.text
        return r.json()

    env.dept = post("/api/v1/org/departments", {"name": "Finance", "code": "FIN"})
    env.general = post("/api/v1/categories", {"name": "General"})
    env.contracts = post(
        "/api/v1/categories",
        {
            "name": "Contracts",
            "default_classification": "confidential",
            "policy": {
                "approval_required": True,
                "required_dimensions": ["department"],
                "allowed_extensions": ["pdf", "docx"],
            },
            "fields": [
                {"key": "ref", "label": "Reference", "field_type": "text", "required": True},
                {"key": "owner", "label": "Owner", "field_type": "employee_lookup"},
            ],
        },
    )
    return env


def reserve(w, h=None, category=None, **over):
    body = {
        "category_id": (category or w.general)["id"],
        "filename": "report.pdf",
        "content_type": "application/pdf",
        "size_bytes": len(PDF),
        **over,
    }
    return w.client.post("/api/v1/documents/uploads", json=body, headers=h or w.emp)


def send(w, version_id, data=PDF, h=None, **headers):
    return w.client.put(
        f"/api/v1/documents/uploads/{version_id}/content",
        content=data,
        headers={**(h or w.emp), **headers},
    )


def upload_ok(w, h=None, data=PDF, category=None, **over):
    r = reserve(w, h, category, size_bytes=len(data), **over)
    assert r.status_code == 201, r.text
    done = send(w, r.json()["version_id"], data, h)
    assert done.status_code == 200, done.text
    return r.json(), done.json()


def row(w, sql, **params):
    with w.engine.connect() as c:
        return c.execute(text(sql), params).all()


def stored_objects(w):
    return [
        p for p in w.storage.root.rglob("*") if p.is_file() and not p.name.endswith(".meta.json")
    ]


def tmp_files(w):
    return list(w.tmp.glob("dms-upload-*"))


# ---- happy path -------------------------------------------------------------------------


def test_upload_end_to_end(world):
    w = world
    session, done = upload_ok(w, title="Q1 report", metadata={})
    assert done["status"] == "available" and done["lifecycle_state"] == "approved"
    assert done["sha256"] == hashlib.sha256(PDF).hexdigest() and done["size_bytes"] == len(PDF)
    assert done["content_type"] == "application/pdf"
    [(key,)] = row(w, "SELECT object_key FROM document_versions")
    assert key.startswith(f"tenants/{w.ta}/documents/{session['document_id']}/versions/1/")
    info = w.storage.stat(key)
    assert info.size_bytes == len(PDF) and info.sha1 == hashlib.sha1(PDF).hexdigest()
    doc = w.client.get(f"/api/v1/documents/{session['document_id']}", headers=w.emp).json()
    assert doc["title"] == "Q1 report" and doc["classification"] == "internal"
    assert doc["current_version_number"] == 1 and doc["versions"][0]["scan_status"] == "clean"
    assert [d["id"] for d in w.client.get("/api/v1/documents/mine", headers=w.emp).json()] == [
        doc["id"]
    ]
    assert tmp_files(w) == []
    log = [
        e["action"]
        for e in w.client.get("/api/v1/audit-events", params={"limit": 100}, headers=w.admin).json()
    ]
    assert "document.upload_requested" in log and "document.uploaded" in log


def test_category_rules_apply_approval_associations_metadata(world):
    w = world
    emp_id = str(w.mem_emp)
    _, done = upload_ok(
        w, category=w.contracts, classification="highly_confidential",
        associations={"department": [w.dept["id"]], "employee": [emp_id]},
        metadata={"ref": "C-2026-01", "owner": emp_id},
    )  # fmt: skip
    assert done["lifecycle_state"] == "submitted"  # category requires approval
    doc = w.client.get("/api/v1/documents/mine", headers=w.emp).json()[0]
    assert doc["classification"] == "highly_confidential"
    assert doc["associations"] == {"department": [w.dept["id"]], "employee": [emp_id]}
    assert doc["metadata"] == {"ref": "C-2026-01", "owner": emp_id}
    assert doc["category_version_number"] == 1 and doc["owner_membership_id"] == emp_id


def test_unicode_filename_title_and_metadata(world):
    w = world
    r = reserve(w, filename="अनुबंध करार.pdf", title="प्रकल्प अहवाल")
    assert r.status_code == 201
    assert send(w, r.json()["version_id"]).status_code == 200
    [(name, key)] = row(w, "SELECT original_filename, object_key FROM document_versions")
    assert name == "अनुबंध करार.pdf" and key.endswith("/अनुबंध करार.pdf")
    assert w.client.get("/api/v1/documents/mine", headers=w.emp).json()[0]["title"] == "प्रकल्प अहवाल"


def test_idempotency_and_repeat_completion(world):
    w = world
    headers = {**w.emp, "Idempotency-Key": "retry-key-0001"}
    first = w.client.post(
        "/api/v1/documents/uploads",
        json={
            "category_id": w.general["id"],
            "filename": "a.pdf",
            "content_type": "application/pdf",
            "size_bytes": len(PDF),
        },
        headers=headers,
    )
    again = w.client.post(
        "/api/v1/documents/uploads",
        json={
            "category_id": w.general["id"],
            "filename": "a.pdf",
            "content_type": "application/pdf",
            "size_bytes": len(PDF),
        },
        headers=headers,
    )
    assert first.status_code == 201 and again.status_code == 200
    assert first.json()["version_id"] == again.json()["version_id"]
    assert row(w, "SELECT count(*) FROM documents") == [(1,)]
    vid = first.json()["version_id"]
    one, two = send(w, vid), send(w, vid)  # the client lost the first response and retried
    assert one.status_code == two.status_code == 200 and one.json() == two.json()
    assert len(stored_objects(w)) == 1
    bad = w.client.post(
        "/api/v1/documents/uploads",
        json={
            "category_id": w.general["id"],
            "filename": "a.pdf",
            "content_type": "application/pdf",
            "size_bytes": 5,
        },
        headers={**w.emp, "Idempotency-Key": "short"},
    )
    assert bad.status_code == 422


# ---- reservation validation -------------------------------------------------------------


@pytest.mark.parametrize(
    ("over", "status", "fragment"),
    [
        (
            {"filename": "run.exe", "content_type": "application/octet-stream"},
            415,
            "extension_not_supported",
        ),
        (
            {"filename": "a.docx", "content_type": "application/octet-stream"},
            None,
            None,
        ),  # ok in General
        ({"content_type": "image/png"}, 415, "mime_mismatch"),
        ({"size_bytes": 10**12}, 413, "size_not_allowed"),
        ({"classification": "secret"}, 422, "classification"),
    ],
)
def test_reservation_rejects_bad_files(world, over, status, fragment):
    r = reserve(world, **over)
    if status is None:
        assert r.status_code == 201
    else:
        assert r.status_code == status and fragment in r.text


def test_reservation_enforces_category_policy(world):
    w = world
    base = {"associations": {"department": [w.dept["id"]]}, "metadata": {"ref": "x"}}
    assert (
        reserve(w, category=w.contracts, filename="a.xlsx", **base).status_code == 415
    )  # not allowed here
    assert (
        reserve(w, category=w.contracts, **{**base, "associations": {}}).status_code == 422
    )  # dept required
    low = reserve(w, category=w.contracts, classification="internal", **base)
    assert low.status_code == 422 and "at least confidential" in low.json()["detail"]
    missing = reserve(w, category=w.contracts, associations=base["associations"], metadata={})
    assert missing.status_code == 422 and missing.json()["detail"]["fields"]["ref"] == "is required"
    wrong = reserve(w, category=w.contracts, associations=base["associations"], metadata={"ref": 5})
    assert wrong.status_code == 422 and "ref" in wrong.json()["detail"]["fields"]
    extra = reserve(
        w, category=w.contracts, associations=base["associations"], metadata={"ref": "x", "zzz": 1}
    )
    assert "zzz" in extra.json()["detail"]["fields"]
    ghost = reserve(
        w,
        category=w.contracts,
        associations={"department": [str(uuid.uuid4())]},
        metadata={"ref": "x"},
    )
    assert ghost.status_code == 422
    assert (
        reserve(
            w, category=w.contracts, associations={"team": [w.dept["id"]]}, metadata={"ref": "x"}
        ).status_code
        == 422
    )
    foreign_owner = reserve(w, owner_membership_id=str(w.mem_admin_b))
    assert foreign_owner.status_code == 422
    ghost_lookup = reserve(w, category=w.contracts, associations=base["associations"],
                           metadata={"ref": "x", "owner": str(uuid.uuid4())})  # fmt: skip
    assert ghost_lookup.status_code == 422
    assert row(w, "SELECT count(*) FROM documents") == [(0,)]  # nothing half-created


def test_tags_and_categories_must_be_valid(world):
    w = world
    system = w.client.get("/api/v1/tags", params={"kind": "system"}, headers=w.emp).json()[0]["id"]
    assert reserve(w, tag_ids=[system]).status_code == 422  # system tags are not user-assignable
    tag = w.client.post(
        "/api/v1/tags", json={"name": "Budget", "kind": "employee"}, headers=w.emp
    ).json()["id"]
    r = reserve(w, tag_ids=[tag])
    assert r.status_code == 201
    assert w.client.get(f"/api/v1/documents/{r.json()['document_id']}", headers=w.emp).json()[
        "tag_ids"
    ] == [tag]
    w.client.patch(
        f"/api/v1/categories/{w.general['id']}", json={"status": "inactive"}, headers=w.admin
    )
    assert reserve(w).status_code == 422
    assert reserve(w, category={"id": str(uuid.uuid4())}).status_code == 422


# ---- content checks, scanning, storage --------------------------------------------------


def test_fake_pdf_is_rejected_and_nothing_is_stored(world):
    w = world
    data = b"MZ\x90\x00 definitely an executable " * 10
    r = reserve(w, size_bytes=len(data))
    bad = send(w, r.json()["version_id"], data)
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "signature_mismatch"
    assert stored_objects(w) == [] and tmp_files(w) == []
    doc = w.client.get(f"/api/v1/documents/{r.json()['document_id']}", headers=w.emp).json()
    assert doc["versions"][0]["status"] == "rejected" and doc["lifecycle_state"] == "draft"
    assert send(w, r.json()["version_id"]).status_code == 409  # a rejected upload is final


def test_size_mismatch_is_rejected(world):
    w = world
    r = reserve(w)
    bad = send(w, r.json()["version_id"], PDF + b"extra bytes")
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "size_mismatch"
    assert stored_objects(w) == [] and tmp_files(w) == []


def test_malware_is_quarantined_and_never_stored(world):
    w = world
    data = PDF + DEV_VIRUS_MARKER
    r = reserve(w, size_bytes=len(data))
    bad = send(w, r.json()["version_id"], data)
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "malware_detected"
    assert stored_objects(w) == [] and tmp_files(w) == []
    doc = w.client.get(f"/api/v1/documents/{r.json()['document_id']}", headers=w.emp).json()
    v = doc["versions"][0]
    assert (v["status"], v["scan_status"], v["reject_reason"]) == (
        "quarantined",
        "infected",
        "malware_detected",
    )
    assert doc["lifecycle_state"] == "draft" and doc["current_version_number"] is None
    assert send(w, r.json()["version_id"]).status_code == 409
    log = w.client.get(
        "/api/v1/audit-events", params={"action": "document.upload_quarantined"}, headers=w.admin
    ).json()
    assert len(log) == 1 and log[0]["outcome"] == "denied"


def test_scanner_outage_blocks_publication_but_allows_retry(world, monkeypatch):
    from app.services.scanner import DevScanner

    w = world
    r = reserve(w)
    vid = r.json()["version_id"]
    outage = {"on": True}

    class Flaky:
        def scan(self, path):
            if outage["on"]:
                return ScanResult("failed", "scanner unreachable")
            return DevScanner().scan(path)

    monkeypatch.setattr("app.api.documents.build_scanner", lambda settings: Flaky())
    out = send(w, vid)
    assert out.status_code == 503 and out.json()["detail"]["code"] == "scan_unavailable"
    assert stored_objects(w) == [] and tmp_files(w) == []  # unscanned files are never stored
    doc = w.client.get(f"/api/v1/documents/{r.json()['document_id']}", headers=w.emp).json()
    assert doc["versions"][0]["status"] == "pending" and doc["lifecycle_state"] == "draft"
    outage["on"] = False
    assert send(w, vid).status_code == 200


def test_storage_failure_keeps_reservation_for_retry(world, monkeypatch):
    w = world
    r = reserve(w)
    vid = r.json()["version_id"]
    real = w.storage.put_file
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise StorageError("storage upload failed (Boom)")
        return real(*a, **kw)

    monkeypatch.setattr(w.storage, "put_file", flaky)
    out = send(w, vid)
    assert out.status_code == 502 and out.json()["detail"]["code"] == "storage_unavailable"
    assert tmp_files(w) == []
    assert send(w, vid).status_code == 200 and len(stored_objects(w)) == 1


def test_concurrent_receive_and_expiry(world):
    w = world
    r = reserve(w)
    vid = r.json()["version_id"]
    with w.engine.begin() as c:
        c.execute(text("UPDATE document_versions SET status='receiving'"))
    assert send(w, vid).status_code == 409
    with w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE document_versions SET status='pending', expires_at = now() - interval '1 minute'"
            )
        )
    assert send(w, vid).status_code == 410
    assert row(w, "SELECT status FROM document_versions") == [("abandoned",)]
    assert send(w, vid).status_code == 409


def test_expire_stale_job_cleans_up_leftovers(world):
    w = world
    reserve(w)
    r2 = reserve(w)
    with w.engine.begin() as c:
        c.execute(text("UPDATE document_versions SET expires_at = now() - interval '1 hour'"))
        c.execute(
            text("UPDATE document_versions SET status='receiving' WHERE id=:i"),
            {"i": r2.json()["version_id"]},
        )
    [(key,)] = row(
        w, "SELECT object_key FROM document_versions WHERE id=:i", i=r2.json()["version_id"]
    )
    w.storage.write_exclusive(key, iter([b"orphan"]), content_type="text/plain", expected_size=6)
    with tenant_session(w.ta, w.engine) as s:
        abandoned, failures = uploads.expire_stale(
            s, w.ta, w.storage, datetime.now(UTC) + timedelta(seconds=1)
        )
    assert (abandoned, failures) == (2, 0)
    assert w.storage.stat(key) is None  # crashed upload's object removed
    assert {s for (s,) in row(w, "SELECT status FROM document_versions")} == {"abandoned"}
    with tenant_session(w.ta, w.engine) as s:
        assert uploads.expire_stale(s, w.ta, w.storage) == (0, 0)  # idempotent


# ---- authorization and isolation --------------------------------------------------------


def test_permissions_and_visibility(world):
    w = world
    assert w.client.post("/api/v1/documents/uploads", json={}).status_code == 401
    with w.engine.begin() as c:
        c.execute(
            text("UPDATE user_role_assignments SET revoked_at = now() WHERE membership_id=:m"),
            {"m": w.mem_emp},
        )
    assert reserve(w, h=w.emp).status_code == 403  # lost upload permission
    r = reserve(w, h=w.admin)  # admin (has document.upload) reserves
    vid = r.json()["version_id"]
    assert send(w, vid, h=w.emp).status_code == 403
    denied = w.client.get(
        "/api/v1/audit-events", params={"action": "authz.denied"}, headers=w.admin
    ).json()
    assert {"document.upload"} <= {e["resource_id"] for e in denied}


def test_uploads_and_documents_are_private_to_their_uploader_for_now(world):
    w = world
    r = reserve(w, h=w.emp)
    vid, doc_id = r.json()["version_id"], r.json()["document_id"]
    assert send(w, vid, h=w.admin).status_code == 404  # cannot complete someone else's upload
    assert w.client.get(f"/api/v1/documents/{doc_id}", headers=w.admin).status_code == 404
    assert w.client.get("/api/v1/documents/mine", headers=w.admin).json() == []
    assert send(w, vid, h=w.emp).status_code == 200


def test_tenants_are_isolated(world):
    w = world
    r = reserve(w, h=w.emp)
    vid, doc_id = r.json()["version_id"], r.json()["document_id"]
    assert send(w, vid, h=w.admin_b).status_code == 404
    assert w.client.get(f"/api/v1/documents/{doc_id}", headers=w.admin_b).status_code == 404
    foreign = reserve(w, h=w.admin_b, category=w.general)  # tenant A's category id in tenant B
    assert foreign.status_code == 422
    assert row(w, "SELECT count(*) FROM documents WHERE tenant_id=:t", t=w.tb) == [(0,)]


# ---- spool ------------------------------------------------------------------------------


def test_spool_hashes_enforces_size_and_cleans_up(tmp_path):
    spool = uploads.Spool(str(tmp_path), 6)
    spool.write(b"abc")
    spool.write(b"def")
    sha1, sha256 = spool.finish()
    assert (
        sha1 == hashlib.sha1(b"abcdef").hexdigest()
        and sha256 == hashlib.sha256(b"abcdef").hexdigest()
    )
    spool.cleanup()
    assert list(tmp_path.iterdir()) == []
    over = uploads.Spool(str(tmp_path), 4)
    with pytest.raises(FileRejected) as exc:
        over.write(b"12345")
    assert exc.value.status == 413
    over.cleanup()
    short = uploads.Spool(str(tmp_path), 9)
    short.write(b"abc")
    with pytest.raises(FileRejected) as exc:
        short.finish()
    assert exc.value.code == "size_mismatch"
    short.cleanup()
    assert list(tmp_path.iterdir()) == []
