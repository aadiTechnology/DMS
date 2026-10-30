# ruff: noqa: F811
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.db.models import DocumentAccessGrant
from app.db.tenant_session import tenant_session
from app.services import access, rbac
from tests.test_rbac import _member, _user, auth, env  # noqa: F401  (fixtures)
from tests.test_uploads import PDF, reserve, send, upload_ok, world  # noqa: F401  (fixtures)


def add_user(w, email, role="employee"):
    with w.engine.begin() as c:
        uid = _user(c, email)
        mid = _member(c, w.ta, uid)
    if role:
        with tenant_session(w.ta, w.engine) as s:
            rbac.assign_role(s, w.ta, w.admin_a, mid, w.roles_a[role])
    return SimpleNamespace(uid=uid, mid=mid, h=auth(w, email))


def put(w, path, body, h=None):
    r = w.client.put(path, json=body, headers=h or w.admin)
    assert r.status_code == 200, r.text


@pytest.fixture
def cast(world):
    """People around one organization: an owner, a stranger, a department manager and member,
    a project manager and member, and a reviewer-style user who cannot download."""
    w = world
    people = SimpleNamespace(
        owner=SimpleNamespace(mid=w.mem_emp, h=w.emp),
        stranger=add_user(w, "stranger@x.test"),
        dm=add_user(w, "dm@x.test"),
        fin=add_user(w, "fin@x.test"),
        pm=add_user(w, "pm@x.test"),
        pmem=add_user(w, "pmem@x.test"),
        rev=add_user(w, "rev@x.test", role="reviewer"),
        norole=add_user(w, "norole@x.test", role=None),
    )
    proj = w.client.post(
        "/api/v1/org/projects", json={"name": "Apollo", "code": "APO"}, headers=w.admin
    ).json()
    w.project = proj
    w.client.patch(
        f"/api/v1/org/departments/{w.dept['id']}",
        json={"manager_membership_id": str(people.dm.mid)},
        headers=w.admin,
    )
    w.client.patch(
        f"/api/v1/org/projects/{proj['id']}",
        json={"manager_membership_id": str(people.pm.mid)},
        headers=w.admin,
    )
    put(
        w,
        f"/api/v1/employees/{people.fin.mid}/profile",
        {"full_name": "Fin", "department_id": w.dept["id"]},
    )
    put(w, f"/api/v1/projects/{proj['id']}/members/{people.pmem.mid}", {})
    w.people = people
    w.memos = w.client.post(
        "/api/v1/categories",
        json={"name": "Memos", "policy": {"approval_required": True}},
        headers=w.admin,
    ).json()
    return w


def make_doc(w, classification, h=None, category=None, **over):
    assoc = {"department": [w.dept["id"]], "project": [w.project["id"]]}
    session, _ = upload_ok(
        w, h or w.emp, category=category, classification=classification, associations=assoc, **over
    )
    return session["document_id"]


def status_of(w, who, doc, suffix=""):
    h = who if isinstance(who, dict) else who.h
    return w.client.get(f"/api/v1/documents/{doc}{suffix}", headers=h).status_code


def can(w, who, doc):
    """(metadata, preview, download) as HTTP status codes."""
    return (
        status_of(w, who, doc),
        status_of(w, who, doc, "/versions/1/preview-url"),
        status_of(w, who, doc, "/versions/1/download-url"),
    )


OK, NO, FORBIDDEN = 200, 404, 403


def test_public_and_internal_documents_are_open_to_the_organization(cast):
    w, p = cast, cast.people
    notices = w.client.post(
        "/api/v1/categories",
        json={"name": "Notices", "default_classification": "public"},
        headers=w.admin,
    ).json()
    for level, category in (("public", notices), ("internal", None)):
        doc = make_doc(w, level, category=category)
        for who in (p.stranger, p.dm, p.fin, p.pm, p.pmem, w.emp):
            assert can(w, who, doc) == (OK, OK, OK), (level, who)


def test_confidential_follows_ownership_department_and_project(cast):
    w, p = cast, cast.people
    doc = make_doc(w, "confidential")
    assert can(w, w.emp, doc) == (OK, OK, OK)  # owner and uploader
    assert can(w, p.dm, doc) == (OK, OK, OK)  # manages the associated department
    assert can(w, p.fin, doc) == (OK, OK, OK)  # works in the associated department
    assert can(w, p.pm, doc) == (OK, OK, OK)  # manages the associated project
    assert can(w, p.pmem, doc) == (OK, OK, OK)  # member of the associated project
    assert can(w, p.stranger, doc) == (NO, NO, NO)  # existence is not revealed
    assert can(w, w.admin_b, doc) == (NO, NO, NO)  # other organization


def test_highly_confidential_is_owner_department_manager_and_grants_only(cast):
    w, p = cast, cast.people
    bob = p.stranger
    doc = make_doc(w, "highly_confidential", h=bob.h, owner_membership_id=str(w.mem_emp))
    assert can(w, w.emp, doc) == (OK, OK, OK)  # owner
    assert can(w, p.dm, doc) == (OK, OK, OK)  # department manager
    assert can(w, bob, doc) == (OK, NO, NO)  # uploader: may follow the upload, not open it
    for who in (p.fin, p.pm, p.pmem):
        assert can(w, who, doc) == (NO, NO, NO)  # department/project members are not enough
    assert can(w, w.admin_b, doc) == (NO, NO, NO)


def test_administrators_reach_everything_through_an_audited_privileged_path(cast):
    w, p = cast, cast.people
    hc = make_doc(w, "highly_confidential")
    pending = make_doc(w, "internal", category=w.memos)
    for doc in (hc, pending):
        assert can(w, w.admin, doc) == (OK, OK, OK)
    events = w.client.get(
        "/api/v1/audit-events",
        params={"action": "document.privileged_access", "limit": 100},
        headers=w.admin,
    ).json()
    accesses = [
        (e["details"]["access"], e["details"]["classification"], e["details"]["basis"])
        for e in events
    ]
    assert ("download", "highly_confidential", "administrator_privilege") in accesses
    assert ("preview", "highly_confidential", "administrator_privilege") in accesses
    assert ("view_metadata", "highly_confidential", "administrator_privilege") in accesses
    assert all(e["privileged"] is True for e in events) and len(events) >= 6
    # administrators who own a document use the normal path, so it is not flagged
    own = make_doc(w, "highly_confidential", h=w.admin)
    before = len(events)
    assert can(w, w.admin, own) == (OK, OK, OK)
    after = w.client.get(
        "/api/v1/audit-events",
        params={"action": "document.privileged_access", "limit": 100},
        headers=w.admin,
    ).json()
    assert len(after) == before
    # and the privilege exists only for holders of the permission
    assert can(w, p.dm, pending) == (NO, NO, NO)


def test_unpublished_documents_are_visible_to_their_uploader_only(cast):
    w, p = cast, cast.people
    pending = make_doc(w, "internal", category=w.memos)
    assert (
        w.client.get(f"/api/v1/documents/{pending}", headers=w.emp).json()["lifecycle_state"]
        == "submitted"
    )
    assert can(w, w.emp, pending) == (OK, OK, OK)
    for who in (p.stranger, p.dm, p.fin):
        assert can(w, who, pending) == (NO, NO, NO)
    with w.engine.begin() as c:
        c.execute(
            text("UPDATE documents SET lifecycle_state='approved' WHERE id=:i"), {"i": pending}
        )
        c.execute(  # the approval workflow does both together; the version gate needs its half
            text("UPDATE document_versions SET review_status='approved' WHERE document_id=:i"),
            {"i": pending},
        )
    assert can(w, p.stranger, pending) == (OK, OK, OK)  # published: now open (internal)
    with w.engine.begin() as c:
        c.execute(
            text("UPDATE documents SET lifecycle_state='rejected' WHERE id=:i"), {"i": pending}
        )
    assert can(w, p.stranger, pending) == (NO, NO, NO)
    with w.engine.begin() as c:
        c.execute(
            text("UPDATE documents SET lifecycle_state='archived' WHERE id=:i"), {"i": pending}
        )
    assert can(w, p.stranger, pending) == (OK, OK, OK)  # archived documents stay reachable


def test_department_and_project_membership_must_be_current(cast):
    w, p = cast, cast.people
    doc = make_doc(w, "confidential")
    assert can(w, p.fin, doc)[0] == OK and can(w, p.pmem, doc)[0] == OK
    put(w, f"/api/v1/employees/{p.fin.mid}/profile", {"employment_status": "exited"})
    assert can(w, p.fin, doc) == (NO, NO, NO)
    with w.engine.begin() as c:
        c.execute(text("UPDATE project_memberships SET ends_on = current_date - 1"))
    assert can(w, p.pmem, doc) == (NO, NO, NO)


def test_direct_shares_are_per_action_and_time_limited(cast):
    w, p = cast, cast.people
    doc = make_doc(w, "confidential")
    bob = p.stranger

    def grant(**kw):
        with tenant_session(w.ta, w.engine) as s:
            row = DocumentAccessGrant(
                tenant_id=w.ta, document_id=doc, grantee_membership_id=bob.mid,
                granted_by_user_id=w.admin_a, **kw,
            )  # fmt: skip
            s.add(row)
            s.flush()
            return row.id

    gid = grant(can_view=True, can_download=False)
    assert can(w, bob, doc) == (OK, OK, NO)  # viewing does not imply downloading
    with w.engine.begin() as c:
        c.execute(
            text("UPDATE document_access_grants SET can_download = true WHERE id=:i"), {"i": gid}
        )
    assert can(w, bob, doc) == (OK, OK, OK)
    with w.engine.begin() as c:
        c.execute(
            text("UPDATE document_access_grants SET revoked_at = now() WHERE id=:i"), {"i": gid}
        )
    assert can(w, bob, doc) == (NO, NO, NO)  # revocation applies on the next request
    past = datetime.now(UTC) - timedelta(minutes=1)
    grant(can_view=True, expires_at=past)
    assert can(w, bob, doc) == (NO, NO, NO)  # expired


def test_a_share_cannot_exceed_the_role_ceiling(cast):
    w, p = cast, cast.people
    doc = make_doc(w, "highly_confidential")
    with tenant_session(w.ta, w.engine) as s:
        s.add(DocumentAccessGrant(
            tenant_id=w.ta, document_id=doc, grantee_membership_id=p.rev.mid,
            granted_by_user_id=w.admin_a, can_view=True, can_download=True,
        ))  # fmt: skip
    assert can(w, p.rev, doc) == (OK, OK, FORBIDDEN)  # reviewers' role has no download right
    assert can(w, p.norole, doc) == (FORBIDDEN, FORBIDDEN, FORBIDDEN)  # no role, no access at all


def test_links_deliver_the_file_with_the_right_disposition(cast, monkeypatch):
    w = cast
    monkeypatch.setattr("app.api.dev_storage.get_storage", lambda: w.storage)
    doc = make_doc(w, "internal")
    dl = w.client.get(f"/api/v1/documents/{doc}/versions/1/download-url", headers=w.emp)
    assert dl.status_code == 200 and dl.headers["cache-control"] == "no-store"
    body = dl.json()
    assert body["expires_in_seconds"] == 300 and body["filename"] == "report.pdf"
    assert body["content_type"] == "application/pdf" and body["size_bytes"] == len(PDF)
    from urllib.parse import urlparse

    got = w.client.get(urlparse(body["url"]).path)
    assert got.content == PDF and got.headers["content-disposition"].startswith("attachment")
    pv = w.client.get(f"/api/v1/documents/{doc}/versions/1/preview-url", headers=w.emp).json()
    shown = w.client.get(urlparse(pv["url"]).path)
    assert shown.content == PDF and shown.headers["content-disposition"].startswith("inline")
    assert shown.headers["x-content-type-options"] == "nosniff"


def test_only_safe_types_have_a_preview_and_missing_versions_are_404(cast):
    w = cast
    r = reserve(w, filename="notes.txt", content_type="text/plain", size_bytes=11)
    assert send(w, r.json()["version_id"], b"hello world").status_code == 200
    doc = r.json()["document_id"]
    pv = w.client.get(f"/api/v1/documents/{doc}/versions/1/preview-url", headers=w.emp)
    assert pv.status_code == 415 and pv.json()["detail"]["code"] == "preview_unavailable"
    assert (
        w.client.get(f"/api/v1/documents/{doc}/versions/1/download-url", headers=w.emp).status_code
        == 200
    )
    assert (
        w.client.get(f"/api/v1/documents/{doc}/versions/2/download-url", headers=w.emp).status_code
        == 404
    )
    pending = reserve(w).json()["document_id"]  # reserved but never uploaded: no available version
    assert (
        w.client.get(
            f"/api/v1/documents/{pending}/versions/1/download-url", headers=w.emp
        ).status_code
        == 404
    )


def test_detail_reports_what_the_caller_may_do(cast):
    w, p = cast, cast.people
    doc = make_doc(w, "highly_confidential", h=p.stranger.h, owner_membership_id=str(w.mem_emp))
    owner_view = w.client.get(f"/api/v1/documents/{doc}", headers=w.emp).json()
    assert owner_view["access"] == {"preview": True, "download": True}
    uploader_view = w.client.get(f"/api/v1/documents/{doc}", headers=p.stranger.h).json()
    assert uploader_view["access"] == {"preview": False, "download": False}


def test_downloads_and_refusals_are_audited_without_leaking_links(cast):
    w, p = cast, cast.people
    doc = make_doc(w, "confidential")
    w.client.get(f"/api/v1/documents/{doc}/versions/1/download-url", headers=w.emp)
    w.client.get(f"/api/v1/documents/{doc}/versions/1/preview-url", headers=p.dm.h)
    assert status_of(w, p.stranger, doc, "/versions/1/download-url") == NO
    log = w.client.get("/api/v1/audit-events", params={"limit": 200}, headers=w.admin).json()
    by_action = {}
    for e in log:
        by_action.setdefault(e["action"], []).append(e)
    dl = next(
        e
        for e in by_action["document.download"]
        if e["details"]["classification"] == "confidential"
    )
    assert (
        dl["details"]["basis"] == "owner"
        and dl["details"]["version"] == 1
        and dl["privileged"] is False
    )
    assert by_action["document.preview"][0]["details"]["basis"] == "department_manager"
    denied = by_action["document.access_denied"][0]
    assert denied["outcome"] == "denied" and denied["details"]["reason"] == "not_authorized"
    assert denied["actor_user_id"] == str(p.stranger.uid)
    assert "http" not in json.dumps(log) and "Authorization" not in json.dumps(log)


def test_unknown_ids_look_the_same_as_forbidden_ones(cast):
    w = cast
    import uuid

    assert status_of(w, w.emp, uuid.uuid4()) == NO
    doc = make_doc(w, "highly_confidential")
    assert status_of(w, cast.people.fin, doc) == NO  # exists but not allowed: identical answer
    assert w.client.get(f"/api/v1/documents/{doc}").status_code == 401


def test_new_permission_reaches_existing_admin_roles_and_is_not_in_other_roles(cast):
    w = cast
    perms = w.client.get("/api/v1/me/permissions", headers=w.admin).json()["permissions"]
    assert "document.access_all" in perms
    for h in (w.emp, cast.people.dm.h, cast.people.rev.h):
        assert (
            "document.access_all"
            not in w.client.get("/api/v1/me/permissions", headers=h).json()["permissions"]
        )


def test_decision_engine_is_deterministic_and_explains_itself(cast):
    w = cast
    doc_id = make_doc(w, "confidential")
    with tenant_session(w.ta, w.engine) as s:
        from app.db.models import Document

        document = s.get(Document, doc_id)
        decision = access.decide(s, w.ta, cast.people.dm.uid, document, "download")
        assert (decision.allowed, decision.reason, decision.privileged) == (
            True,
            "department_manager",
            False,
        )
        denied = access.decide(s, w.ta, cast.people.stranger.uid, document, "download")
        assert (denied.allowed, denied.reason) == (False, "not_authorized")
        other = access.decide(s, w.tb, cast.people.dm.uid, document, "download")
        assert other.reason == "other_tenant"
