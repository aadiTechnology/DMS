# ruff: noqa: F811
import hashlib
import uuid
from urllib.parse import urlparse

import pytest
from sqlalchemy import text

from app.db.models import DocumentAccessGrant
from app.db.tenant_session import tenant_session
from tests.samples import make_pdf
from tests.test_access import add_user, cast  # noqa: F401  (fixtures)
from tests.test_rbac import auth, env  # noqa: F401
from tests.test_uploads import reserve, send, world  # noqa: F401  (fixtures)


@pytest.fixture(autouse=True)
def serve_local_files(monkeypatch, world):
    monkeypatch.setattr("app.api.dev_storage.get_storage", lambda: world.storage)


def first_doc(
    w,
    h=None,
    data=b"first version text",
    name="notes.txt",
    category=None,
    ctype="text/plain",
    **over,
):
    r = reserve(
        w,
        h or w.emp,
        category=category,
        filename=name,
        content_type=ctype,
        size_bytes=len(data),
        **over,
    )
    assert r.status_code == 201, r.text
    assert send(w, r.json()["version_id"], data, h or w.emp).status_code == 200
    return r.json()["document_id"]


def add_version(
    w, h, doc, data, based_on, name="notes.txt", expect=201, ctype="text/plain", **extra
):
    body = {
        "filename": name,
        "content_type": ctype,
        "size_bytes": len(data),
        "based_on_version": based_on,
        **extra,
    }
    r = w.client.post(f"/api/v1/documents/{doc}/versions/uploads", json=body, headers=h)
    assert r.status_code == expect, r.text
    if expect != 201:
        return r
    done = send(w, r.json()["version_id"], data, h)
    assert done.status_code == 200, done.text
    return done.json()


def detail(w, h, doc):
    r = w.client.get(f"/api/v1/documents/{doc}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def fetch(w, h, doc, number, action="download"):
    r = w.client.get(f"/api/v1/documents/{doc}/versions/{number}/{action}-url", headers=h)
    if r.status_code != 200:
        return r.status_code, None
    return 200, w.client.get(urlparse(r.json()["url"]).path).content


def approve_by_hand(w, doc, number):
    """Stand-in for the approval workflow (next sprint): mark a version and document approved."""
    with w.engine.begin() as c:
        c.execute(  # close the review the upload opened, as the workflow would
            text(
                "UPDATE approval_requests SET status='approved' WHERE document_id=:d AND status='pending'"
            ),
            {"d": doc},
        )
        c.execute(
            text(
                "UPDATE document_versions SET review_status='approved' WHERE document_id=:d AND version_number=:n"
            ),
            {"d": doc, "n": number},
        )
        c.execute(
            text(
                "UPDATE documents SET lifecycle_state='approved', current_version_number=:n WHERE id=:d"
            ),
            {"d": doc, "n": number},
        )


# ---- new versions -----------------------------------------------------------------------


def test_new_version_keeps_history_and_becomes_current(world):
    w = world
    doc = first_doc(w, data=b"version one text")
    done = add_version(
        w, w.emp, doc, b"version two text, longer", based_on=1, comment="fixed typos"
    )
    assert done["status"] == "available" and done["lifecycle_state"] == "approved"
    d = detail(w, w.emp, doc)
    assert d["current_version_number"] == 2 and d["row_version"] > 1
    listed = w.client.get(f"/api/v1/documents/{doc}/versions", headers=w.emp).json()
    assert [v["version_number"] for v in listed] == [2, 1]
    assert listed[0]["comment"] == "fixed typos" and listed[0]["review_status"] == "none"
    assert fetch(w, w.emp, doc, 1) == (200, b"version one text")  # history is retrievable
    assert fetch(w, w.emp, doc, 2) == (200, b"version two text, longer")
    keys = [
        k
        for (k,) in w.engine.connect().execute(
            text("SELECT object_key FROM document_versions ORDER BY version_number")
        )
    ]
    assert len(set(keys)) == 2 and all(
        w.storage.stat(k) for k in keys
    )  # distinct immutable objects
    assert w.storage.stat(keys[0]).sha1 == hashlib.sha1(b"version one text").hexdigest()


def test_search_follows_the_current_version(world):
    w = world
    doc = first_doc(w, data=b"alphaword in the first version")
    add_version(w, w.emp, doc, b"betaword in the second version", based_on=1)
    hit = lambda q: w.client.get("/api/v1/search", params={"q": q}, headers=w.emp).json()["total"]
    assert hit("betaword") == 1 and hit("alphaword") == 0


def test_concurrent_updates_are_refused_not_overwritten(world):
    w = world
    doc = first_doc(w)
    add_version(w, w.emp, doc, b"second", based_on=1)
    stale = add_version(w, w.emp, doc, b"third from old screen", based_on=1, expect=409)
    assert stale.json()["detail"] == {
        "code": "stale",
        "message": stale.json()["detail"]["message"],
        "latest_version": 2,
    }
    r1 = w.client.post(
        f"/api/v1/documents/{doc}/versions/uploads",
        json={
            "filename": "a.txt",
            "content_type": "text/plain",
            "size_bytes": 5,
            "based_on_version": 2,
        },
        headers=w.emp,
    )
    r2 = w.client.post(
        f"/api/v1/documents/{doc}/versions/uploads",
        json={
            "filename": "b.txt",
            "content_type": "text/plain",
            "size_bytes": 5,
            "based_on_version": 2,
        },
        headers=w.emp,
    )
    assert r1.status_code == 201 and r2.status_code == 409
    assert r2.json()["detail"]["code"] == "stale"  # the reservation already took number 3
    r3 = w.client.post(
        f"/api/v1/documents/{doc}/versions/uploads",
        json={
            "filename": "c.txt",
            "content_type": "text/plain",
            "size_bytes": 5,
            "based_on_version": 3,
        },
        headers=w.emp,
    )
    assert r3.status_code == 409 and "in progress" in r3.json()["detail"]
    assert detail(w, w.emp, doc)["current_version_number"] == 2


def test_new_version_is_idempotent_and_validated(world):
    w = world
    doc = first_doc(w)
    body = {
        "filename": "v2.txt",
        "content_type": "text/plain",
        "size_bytes": 3,
        "based_on_version": 1,
    }
    h = {**w.emp, "Idempotency-Key": "version-retry-0001"}
    a = w.client.post(f"/api/v1/documents/{doc}/versions/uploads", json=body, headers=h)
    b = w.client.post(f"/api/v1/documents/{doc}/versions/uploads", json=body, headers=h)
    assert (
        a.status_code == 201
        and b.status_code == 200
        and a.json()["version_id"] == b.json()["version_id"]
    )
    other = first_doc(w, name="b.txt")
    for bad, code in (
        ({"filename": "run.exe", "content_type": "application/octet-stream"}, 415),
        ({"content_type": "image/png"}, 415),
        ({"size_bytes": 10**12}, 413),
    ):
        r = w.client.post(
            f"/api/v1/documents/{other}/versions/uploads", json={**body, **bad}, headers=w.emp
        )
        assert r.status_code == code, (bad, r.text)
    missing = {k: v for k, v in body.items() if k != "based_on_version"}
    assert (
        w.client.post(
            f"/api/v1/documents/{other}/versions/uploads", json=missing, headers=w.emp
        ).status_code
        == 422
    )


def test_bad_bytes_for_a_new_version_are_rejected_without_touching_history(world):
    w = world
    doc = first_doc(w, name="n.pdf", data=make_pdf("genuine"), ctype="application/pdf")
    fake = b"MZ not a pdf at all " * 5
    r = w.client.post(
        f"/api/v1/documents/{doc}/versions/uploads",
        json={
            "filename": "n.pdf",
            "content_type": "application/pdf",
            "size_bytes": len(fake),
            "based_on_version": 1,
        },
        headers=w.emp,
    )
    assert send(w, r.json()["version_id"], fake).status_code == 422
    d = detail(w, w.emp, doc)
    assert d["current_version_number"] == 1 and [v["status"] for v in d["versions"]] == [
        "available",
        "rejected",
    ]
    stranger = w.client.get(
        f"/api/v1/documents/{doc}/versions", headers=add_user(w, "peek@x.test").h
    ).json()
    assert [v["version_number"] for v in stranger] == [
        1
    ]  # failed uploads are private to the uploader


# ---- restore ----------------------------------------------------------------------------


def test_restore_creates_a_new_version_from_an_old_one(world):
    w = world
    doc = first_doc(w, data=b"the original wording")
    add_version(w, w.emp, doc, b"a worse rewrite", based_on=1)
    r = w.client.post(
        f"/api/v1/documents/{doc}/versions/1/restore", json={"based_on_version": 2}, headers=w.emp
    )
    assert r.status_code == 200 and r.json()["status"] == "available"
    d = detail(w, w.emp, doc)
    assert d["current_version_number"] == 3
    v3 = d["versions"][-1]
    assert v3["restored_from_version"] == 1 and v3["comment"] == "Restored from version 1"
    assert fetch(w, w.emp, doc, 3) == (200, b"the original wording")
    assert fetch(w, w.emp, doc, 2) == (200, b"a worse rewrite")  # history untouched
    rows = (
        w.engine.connect()
        .execute(text("SELECT sha256, object_key FROM document_versions ORDER BY version_number"))
        .all()
    )
    assert (
        rows[0][0] == rows[2][0] and len({k for _, k in rows}) == 3
    )  # same content, separate objects
    assert (
        w.client.get("/api/v1/search", params={"q": "wording"}, headers=w.emp).json()["total"] == 1
    )
    stale = w.client.post(
        f"/api/v1/documents/{doc}/versions/1/restore", json={"based_on_version": 2}, headers=w.emp
    )
    assert stale.status_code == 409 and stale.json()["detail"]["latest_version"] == 3
    log = [
        e["action"]
        for e in w.client.get("/api/v1/audit-events", params={"limit": 200}, headers=w.admin).json()
    ]
    assert log.count("document.uploaded") == 3


def test_restore_rules(world):
    w = world
    doc = first_doc(w)
    assert (
        w.client.post(
            f"/api/v1/documents/{doc}/versions/9/restore",
            json={"based_on_version": 1},
            headers=w.emp,
        ).status_code
        == 404
    )
    stranger = add_user(w, "s@x.test")
    assert (
        w.client.post(
            f"/api/v1/documents/{doc}/versions/1/restore",
            json={"based_on_version": 1},
            headers=stranger.h,
        ).status_code
        == 404
    )
    assert (
        w.client.post(
            f"/api/v1/documents/{doc}/versions/1/restore",
            json={"based_on_version": 1},
            headers=w.admin_b,
        ).status_code
        == 404
    )
    norole = add_user(w, "n@x.test", role=None)
    assert (
        w.client.post(
            f"/api/v1/documents/{doc}/versions/1/restore",
            json={"based_on_version": 1},
            headers=norole.h,
        ).status_code
        == 403
    )
    junk = b"MZ\x90\x00 not a pdf at all, just nonsense"
    bad = reserve(w, filename="x.pdf", content_type="application/pdf", size_bytes=len(junk))
    assert send(w, bad.json()["version_id"], junk, w.emp).status_code == 422
    assert (
        w.client.post(
            f"/api/v1/documents/{bad.json()['document_id']}/versions/1/restore",
            json={"based_on_version": 1},
            headers=w.emp,
        ).status_code
        == 409
    )  # never published


# ---- approval gate ----------------------------------------------------------------------


def test_later_versions_wait_for_approval_and_readers_keep_the_approved_one(cast):
    w = cast
    stranger = add_user(w, "reader@x.test")
    doc = first_doc(w, category=w.memos, data=b"approved first draft")
    approve_by_hand(w, doc, 1)
    assert (
        add_version(w, w.emp, doc, b"a second draft awaiting review", based_on=1)["lifecycle_state"]
        == "approved"
    )
    d = detail(w, w.emp, doc)
    assert d["current_version_number"] == 1  # unchanged until approved
    assert [(v["version_number"], v["review_status"]) for v in d["versions"]] == [
        (1, "approved"),
        (2, "pending"),
    ]
    assert fetch(w, stranger.h, doc, 1) == (200, b"approved first draft")
    assert fetch(w, stranger.h, doc, 2) == (
        404,
        None,
    )  # general readers never get unreviewed content
    assert fetch(w, w.emp, doc, 2) == (200, b"a second draft awaiting review")  # its uploader does
    assert fetch(w, w.admin, doc, 2) == (
        200,
        b"a second draft awaiting review",
    )  # privileged, audited
    assert [v["version_number"] for v in detail(w, stranger.h, doc)["versions"]] == [1]
    third = add_version(w, w.emp, doc, b"third", based_on=2, expect=409)
    assert "awaiting approval" in third.json()["detail"]
    restore = w.client.post(
        f"/api/v1/documents/{doc}/versions/1/restore", json={"based_on_version": 2}, headers=w.emp
    )
    assert restore.status_code == 409
    hit = w.client.get("/api/v1/search", params={"q": "awaiting"}, headers=w.emp).json()["total"]
    assert hit == 0  # unreviewed text is not indexed as the document's content


# ---- who may add versions ---------------------------------------------------------------


def test_only_owner_uploader_or_privileged_admin_can_add_versions(world):
    w = world
    doc = first_doc(w, data=b"owned by the employee")
    stranger = add_user(w, "other@x.test")
    r = add_version(w, stranger.h, doc, b"hijack", based_on=1, expect=404)
    assert r.status_code == 404
    denied = w.client.get(
        "/api/v1/audit-events", params={"action": "document.access_denied"}, headers=w.admin
    ).json()
    assert any(e["details"]["access"] == "upload_version" for e in denied)
    add_version(w, w.admin, doc, b"administrator correction", based_on=1)
    priv = w.client.get(
        "/api/v1/audit-events",
        params={"action": "document.version_upload_requested"},
        headers=w.admin,
    ).json()
    assert (
        priv[0]["privileged"] is True and priv[0]["details"]["basis"] == "administrator_privilege"
    )
    assert add_version(w, w.admin_b, doc, b"x", based_on=2, expect=404).status_code == 404
    assert w.client.post(f"/api/v1/documents/{doc}/versions/uploads", json={}).status_code == 401


def test_uploader_cannot_modify_a_highly_confidential_document_they_do_not_own(world):
    w = world
    bob = add_user(w, "bob@x.test")
    doc = first_doc(
        w, h=bob.h, classification="highly_confidential", owner_membership_id=str(w.mem_emp)
    )
    assert add_version(w, bob.h, doc, b"update", based_on=1, expect=404).status_code == 404
    assert add_version(w, w.emp, doc, b"owner update", based_on=1)["status"] == "available"


def test_archived_documents_and_switched_off_categories_block_new_versions(world):
    w = world
    doc = first_doc(w)
    with w.engine.begin() as c:
        c.execute(text("UPDATE documents SET lifecycle_state='archived' WHERE id=:d"), {"d": doc})
    assert "archive" in add_version(w, w.emp, doc, b"x", based_on=1, expect=409).json()["detail"]
    with w.engine.begin() as c:
        c.execute(text("UPDATE documents SET lifecycle_state='approved' WHERE id=:d"), {"d": doc})
    w.client.patch(
        f"/api/v1/categories/{w.general['id']}", json={"status": "inactive"}, headers=w.admin
    )
    assert (
        "switched off" in add_version(w, w.emp, doc, b"x", based_on=1, expect=409).json()["detail"]
    )


def test_old_versions_never_bypass_current_authorization(world):
    w = world
    bob = add_user(w, "share@x.test")
    doc = first_doc(w, data=b"confidential v1", classification="confidential")
    with tenant_session(w.ta, w.engine) as s:
        grant = DocumentAccessGrant(
            tenant_id=w.ta,
            document_id=doc,
            grantee_membership_id=bob.mid,
            granted_by_user_id=w.admin_a,
            can_view=True,
            can_download=True,
        )
        s.add(grant)
        s.flush()
        gid = grant.id
    add_version(w, w.emp, doc, b"confidential v2", based_on=1)
    assert fetch(w, bob.h, doc, 1) == (200, b"confidential v1")
    with w.engine.begin() as c:
        c.execute(
            text("UPDATE document_access_grants SET revoked_at=now() WHERE id=:i"), {"i": gid}
        )
    assert fetch(w, bob.h, doc, 1) == (404, None) and fetch(w, bob.h, doc, 2) == (404, None)


# ---- metadata edits ---------------------------------------------------------------------


@pytest.fixture
def invoices(world):
    w = world
    cat = w.client.post(
        "/api/v1/categories",
        json={"name": "Invoices", "fields": [
            {"key": "vendor", "label": "Vendor", "field_type": "text", "required": True},
            {"key": "note", "label": "Note", "field_type": "text"},
        ]},
        headers=w.admin,
    ).json()  # fmt: skip
    r = reserve(
        w,
        category=cat,
        filename="i.txt",
        content_type="text/plain",
        size_bytes=7,
        metadata={"vendor": "Acme Corp", "note": "first"},
        title="Invoice 1",
    )
    assert send(w, r.json()["version_id"], b"invoice", w.emp).status_code == 200
    w.inv = r.json()["document_id"]
    return w


def edit(w, h, doc, **body):
    return w.client.patch(f"/api/v1/documents/{doc}", json=body, headers=h)


def test_edit_title_metadata_and_tags_with_row_version(invoices):
    w = invoices
    d = detail(w, w.emp, w.inv)
    rv = d["row_version"]
    tag = w.client.post(
        "/api/v1/tags", json={"name": "Reviewed", "kind": "employee"}, headers=w.emp
    ).json()["id"]
    r = edit(
        w,
        w.emp,
        w.inv,
        row_version=rv,
        title="Invoice 1 (final)",
        metadata={"vendor": "Zenith Ltd", "note": None},
        tag_ids=[tag],
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["title"] == "Invoice 1 (final)" and out["metadata"] == {
        "vendor": "Zenith Ltd"
    }  # null removed 'note'
    assert out["tag_ids"] == [tag] and out["row_version"] == rv + 1
    hit = lambda q: w.client.get("/api/v1/search", params={"q": q}, headers=w.emp).json()["total"]
    assert hit("zenith") == 1 and hit("acme") == 0 and hit("final") == 1 and hit("reviewed") == 1
    again = edit(w, w.emp, w.inv, row_version=out["row_version"], title="Invoice 1 (final)")
    assert (
        again.status_code == 200 and again.json()["row_version"] == out["row_version"]
    )  # no change, no new version
    log = w.client.get(
        "/api/v1/audit-events", params={"action": "document.metadata_updated"}, headers=w.admin
    ).json()
    assert len(log) == 1 and log[0]["details"]["changed"] == ["metadata", "tags", "title"]
    assert "Zenith" not in str(log)  # the audit trail records what changed, not the values


def test_stale_edits_are_refused_and_nothing_is_lost(invoices):
    w = invoices
    rv = detail(w, w.emp, w.inv)["row_version"]
    assert edit(w, w.emp, w.inv, row_version=rv, title="Edit by first screen").status_code == 200
    stale = edit(w, w.emp, w.inv, row_version=rv, title="Edit by second screen")
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale"
    assert stale.json()["detail"]["row_version"] == rv + 1
    assert detail(w, w.emp, w.inv)["title"] == "Edit by first screen"


def test_edit_validation(invoices):
    w = invoices
    rv = detail(w, w.emp, w.inv)["row_version"]
    removed = edit(w, w.emp, w.inv, row_version=rv, metadata={"vendor": None})
    assert (
        removed.status_code == 422 and removed.json()["detail"]["fields"]["vendor"] == "is required"
    )
    assert (
        "not a field"
        in edit(w, w.emp, w.inv, row_version=rv, metadata={"zzz": 1}).json()["detail"]["fields"][
            "zzz"
        ]
    )
    assert edit(w, w.emp, w.inv, row_version=rv, title="  ").status_code == 422
    assert edit(w, w.emp, w.inv, row_version=rv, title="x" * 301).status_code == 422
    system = w.client.get("/api/v1/tags", params={"kind": "system"}, headers=w.emp).json()[0]["id"]
    assert edit(w, w.emp, w.inv, row_version=rv, tag_ids=[system]).status_code == 422
    assert edit(w, w.emp, w.inv, row_version=rv, tag_ids=[str(uuid.uuid4())]).status_code == 422
    assert edit(w, w.emp, w.inv, title="no row version").status_code == 422
    assert detail(w, w.emp, w.inv)["row_version"] == rv  # failed edits change nothing


def test_edit_permissions_and_state(invoices):
    w = invoices
    rv = detail(w, w.emp, w.inv)["row_version"]
    stranger = add_user(w, "edit@x.test")
    assert edit(w, stranger.h, w.inv, row_version=rv, title="x").status_code == 404
    assert (
        edit(w, add_user(w, "nr@x.test", role=None).h, w.inv, row_version=rv, title="x").status_code
        == 403
    )
    assert edit(w, w.admin_b, w.inv, row_version=rv, title="x").status_code == 404
    assert (
        edit(w, w.admin, w.inv, row_version=rv, title="Edited by an administrator").status_code
        == 200
    )
    priv = w.client.get(
        "/api/v1/audit-events", params={"action": "document.metadata_updated"}, headers=w.admin
    ).json()
    assert priv[0]["privileged"] is True
    with w.engine.begin() as c:
        c.execute(text("UPDATE documents SET lifecycle_state='archived' WHERE id=:d"), {"d": w.inv})
    assert edit(w, w.emp, w.inv, row_version=rv + 1, title="late").status_code == 409


def test_edits_keep_the_schema_version_the_document_was_created_under(invoices):
    w = invoices
    cats = w.client.get("/api/v1/categories", headers=w.admin).json()
    cid = next(c["id"] for c in cats if c["name"] == "Invoices")
    w.client.post(
        f"/api/v1/categories/{cid}/versions",
        json={
            "fields": [{"key": "po_number", "label": "PO", "field_type": "text", "required": True}]
        },
        headers=w.admin,
    )
    rv = detail(w, w.emp, w.inv)["row_version"]
    ok = edit(w, w.emp, w.inv, row_version=rv, metadata={"note": "still valid under version 1"})
    assert ok.status_code == 200  # the new mandatory PO field does not apply to older documents
    assert detail(w, w.emp, w.inv)["category_version_number"] == 1
