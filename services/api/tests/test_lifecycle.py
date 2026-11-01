# ruff: noqa: F811
from datetime import UTC, datetime, timedelta

import pytest

from tests.test_access import add_user, cast, make_doc  # noqa: F401  (fixtures)
from tests.test_rbac import auth, env  # noqa: F401
from tests.test_uploads import world  # noqa: F401


@pytest.fixture(autouse=True)
def storage_for_deletes(monkeypatch, world):
    monkeypatch.setattr("app.api.lifecycle.get_storage", lambda: world.storage)
    monkeypatch.setattr("app.api.versions.get_storage", lambda: world.storage)


def life(w, h, doc):
    r = w.client.get(f"/api/v1/documents/{doc}/lifecycle", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def post(w, h, path, **body):
    return w.client.post(f"/api/v1/{path}", json=body or None, headers=h)


def category_with(w, **policy):
    r = w.client.post(
        "/api/v1/categories",
        json={"name": f"Cat{len(policy)}{id(policy)}", "policy": policy},
        headers=w.admin,
    )
    assert r.status_code == 201, r.text
    return r.json()


def object_keys(w, doc):
    with w.engine.begin() as c:
        rows = c.exec_driver_sql(
            "SELECT object_key FROM document_versions WHERE document_id = %s", (doc,)
        ).all()
    return [r[0] for r in rows]


def exists(w, key):
    return w.storage.stat(key) is not None


# ---- retention and review clocks --------------------------------------------------------


def test_clock_starts_at_release_from_the_category_version(cast):
    w = cast
    cat = category_with(w, retention_days=30, review_interval_days=10)
    doc = make_doc(w, "internal", category=cat)
    d = life(w, w.emp, doc)
    assert d["retention_until"] == (datetime.now(UTC).date() + timedelta(days=30)).isoformat()
    assert d["review_due_on"] == (datetime.now(UTC).date() + timedelta(days=10)).isoformat()
    assert d["deletion_blockers"][0]["code"] == "retention"
    plain = make_doc(w, "internal")
    assert life(w, w.emp, plain)["retention_until"] is None


def test_clock_starts_only_when_an_approval_category_document_is_approved(cast):
    w, p = cast, cast.people
    cat = category_with(w, approval_required=True, retention_days=5)
    doc = make_doc(w, "internal", category=cat)
    assert life(w, w.emp, doc)["retention_until"] is None  # still waiting for review
    rid = w.client.get(f"/api/v1/documents/{doc}/approvals", headers=w.emp).json()[0]["id"]
    assert post(w, p.rev.h, f"approvals/{rid}/approve").status_code == 200
    assert (
        life(w, w.emp, doc)["retention_until"]
        == (datetime.now(UTC).date() + timedelta(days=5)).isoformat()
    )


# ---- archive ----------------------------------------------------------------------------


def test_archive_and_restore(cast):
    w, p = cast, cast.people
    doc = make_doc(w, "internal")
    assert post(w, p.stranger.h, f"documents/{doc}/archive").status_code == 403  # role lacks it
    assert post(w, p.norole.h, f"documents/{doc}/archive").status_code == 403
    assert post(w, w.emp, f"documents/{doc}/archive").status_code == 403  # employee role lacks it
    assert post(w, w.admin, f"documents/{doc}/archive").status_code == 200
    d = life(w, w.emp, doc)
    assert d["lifecycle_state"] == "archived" and d["archived_at"]
    assert post(w, w.admin, f"documents/{doc}/archive").status_code == 409
    assert (
        w.client.get(f"/api/v1/documents/{doc}", headers=p.stranger.h).status_code == 200
    )  # still readable
    version = w.client.get(f"/api/v1/documents/{doc}", headers=w.emp).json()["row_version"]
    edit = w.client.patch(
        f"/api/v1/documents/{doc}", json={"row_version": version, "title": "x"}, headers=w.emp
    )
    assert edit.status_code == 409  # closed to edits
    assert post(w, w.emp, f"documents/{doc}/unarchive").status_code == 403
    assert post(w, w.admin, f"documents/{doc}/unarchive").status_code == 200
    assert life(w, w.emp, doc)["lifecycle_state"] == "approved"
    assert post(w, w.admin, f"documents/{doc}/unarchive").status_code == 409
    log = {
        e["action"]
        for e in w.client.get("/api/v1/audit-events", params={"limit": 100}, headers=w.admin).json()
    }
    assert {"document.archived", "document.unarchived"} <= log


def test_pending_review_blocks_archiving(cast):
    w = cast
    cat = category_with(w, approval_required=True)
    doc = make_doc(w, "internal", category=cat)  # still under first review: not released
    assert post(w, w.admin, f"documents/{doc}/archive").status_code == 409


# ---- legal hold -------------------------------------------------------------------------


def test_legal_hold_blocks_deletion_until_released(cast):
    w = cast
    doc = make_doc(w, "internal")
    assert post(w, w.emp, f"documents/{doc}/legal-hold", reason="case 12").status_code == 403
    assert post(w, w.admin, f"documents/{doc}/legal-hold").status_code == 422
    assert post(w, w.admin, f"documents/{doc}/legal-hold", reason="  ").status_code == 422
    placed = post(w, w.admin, f"documents/{doc}/legal-hold", reason="Litigation 2026-14")
    assert (
        placed.status_code == 201 and placed.json()["legal_hold"]["reason"] == "Litigation 2026-14"
    )
    assert post(w, w.admin, f"documents/{doc}/legal-hold", reason="again").status_code == 409
    blocked = post(w, w.emp, f"documents/{doc}/deletion-requests", reason="clean up")
    assert blocked.status_code == 409 and "legal hold" in blocked.json()["detail"]
    released = w.client.request(
        "DELETE",
        f"/api/v1/documents/{doc}/legal-hold",
        json={"reason": "Case closed"},
        headers=w.admin,
    )
    assert released.status_code == 200 and released.json()["legal_hold"] is None
    assert (
        w.client.request(
            "DELETE",
            f"/api/v1/documents/{doc}/legal-hold",
            json={"reason": "again"},
            headers=w.admin,
        ).status_code
        == 404
    )
    assert (
        post(w, w.emp, f"documents/{doc}/deletion-requests", reason="clean up").status_code == 201
    )
    log = {
        e["action"]
        for e in w.client.get("/api/v1/audit-events", params={"limit": 100}, headers=w.admin).json()
    }
    assert {
        "document.legal_hold_placed",
        "document.legal_hold_released",
        "deletion.requested",
    } <= log


# ---- deletion ---------------------------------------------------------------------------


def test_retention_blocks_deletion_requests(cast):
    w = cast
    doc = make_doc(w, "internal", category=category_with(w, retention_days=30))
    blocked = post(w, w.emp, f"documents/{doc}/deletion-requests", reason="old")
    assert blocked.status_code == 409 and "retention until" in blocked.json()["detail"]
    with w.engine.begin() as c:
        c.exec_driver_sql("UPDATE documents SET retention_until = current_date - 1")
    assert post(w, w.emp, f"documents/{doc}/deletion-requests", reason="old").status_code == 201


def test_approved_deletion_removes_files_and_leaves_a_tombstone(cast):
    w, p = cast, cast.people
    doc = make_doc(w, "internal")
    keys = object_keys(w, doc)
    assert keys and all(exists(w, k) for k in keys)
    assert (
        post(w, p.stranger.h, f"documents/{doc}/deletion-requests", reason="x").status_code == 404
    )
    assert post(w, w.emp, f"documents/{doc}/deletion-requests", reason="").status_code == 422
    req = post(w, w.emp, f"documents/{doc}/deletion-requests", reason="Duplicate upload")
    assert req.status_code == 201
    rid = req.json()["id"]
    assert post(w, w.emp, f"documents/{doc}/deletion-requests", reason="again").status_code == 409
    assert life(w, w.emp, doc)["deletion_request"]["id"] == rid
    assert (
        post(w, w.emp, f"deletion-requests/{rid}/approve").status_code == 403
    )  # no right to approve
    queue = w.client.get("/api/v1/deletion-requests", headers=w.admin).json()
    assert [(q["id"], q["title"]) for q in queue] == [(rid, "m")] or [q["id"] for q in queue] == [
        rid
    ]
    assert w.client.get("/api/v1/deletion-requests", headers=w.emp).status_code == 403
    done = post(w, w.admin, f"deletion-requests/{rid}/approve", reason="Confirmed duplicate")
    assert done.status_code == 200 and done.json()["status"] == "approved"
    assert not any(exists(w, k) for k in keys)  # the files are gone
    for who in (w.emp, w.admin, p.stranger.h):
        assert w.client.get(f"/api/v1/documents/{doc}", headers=who).status_code == 404
    assert (
        w.client.get("/api/v1/search", params={"limit": 100}, headers=w.admin).json()["total"] == 0
    )
    with w.engine.begin() as c:  # tombstone stays for history
        row = c.exec_driver_sql(
            "SELECT lifecycle_state, deleted_at IS NOT NULL FROM documents WHERE id = %s", (doc,)
        ).one()
        purged = c.exec_driver_sql(
            "SELECT count(*) FROM document_versions WHERE document_id = %s AND purged_at IS NOT NULL",
            (doc,),
        ).scalar()
    assert tuple(row) == ("deleted", True) and purged == len(keys)
    assert post(w, w.admin, f"deletion-requests/{rid}/approve").status_code == 404
    log = {
        e["action"]
        for e in w.client.get("/api/v1/audit-events", params={"limit": 200}, headers=w.admin).json()
    }
    assert {"deletion.requested", "deletion.approved"} <= log


def test_deleting_closes_shares(cast):
    w, p = cast, cast.people
    doc = make_doc(w, "confidential")
    w.client.post(
        f"/api/v1/documents/{doc}/shares",
        json={"grantee_membership_id": str(p.stranger.mid)},
        headers=w.emp,
    )
    rid = post(w, w.emp, f"documents/{doc}/deletion-requests", reason="gone").json()["id"]
    assert post(w, w.admin, f"deletion-requests/{rid}/approve").status_code == 200
    assert w.client.get("/api/v1/shares/with-me", headers=p.stranger.h).json() == []
    assert (
        w.client.get(f"/api/v1/documents/{doc}/shares?history=true", headers=w.emp).status_code
        == 404
    )


def test_nobody_decides_their_own_deletion_request(cast):
    w = cast
    doc = make_doc(w, "internal", h=w.admin)  # an administrator uploads and owns it
    rid = post(w, w.admin, f"documents/{doc}/deletion-requests", reason="oops").json()["id"]
    own = post(w, w.admin, f"deletion-requests/{rid}/approve")
    assert own.status_code == 403 and "own" in own.json()["detail"]
    assert life(w, w.admin, doc)["lifecycle_state"] == "approved"
    other = add_user(w, "custodian@x.test", role="org_admin")
    assert post(w, other.h, f"deletion-requests/{rid}/approve").status_code == 200


def test_rejecting_and_cancelling(cast):
    w, p = cast, cast.people
    doc = make_doc(w, "internal")
    rid = post(w, w.emp, f"documents/{doc}/deletion-requests", reason="tidy").json()["id"]
    assert post(w, w.admin, f"deletion-requests/{rid}/reject").status_code == 422  # reason needed
    rejected = post(w, w.admin, f"deletion-requests/{rid}/reject", reason="Still needed")
    assert rejected.status_code == 200 and rejected.json()["decision_reason"] == "Still needed"
    assert life(w, w.emp, doc)["lifecycle_state"] == "approved"
    assert post(w, w.admin, f"deletion-requests/{rid}/reject", reason="again").status_code == 409
    again = post(w, w.emp, f"documents/{doc}/deletion-requests", reason="second try").json()["id"]
    assert post(w, p.stranger.h, f"deletion-requests/{again}/cancel").status_code == 404
    assert post(w, w.emp, f"deletion-requests/{again}/cancel").json()["status"] == "cancelled"
    assert post(w, w.emp, f"deletion-requests/{again}/cancel").status_code == 409


def test_hold_placed_after_the_request_blocks_the_approval(cast):
    w = cast
    doc = make_doc(w, "internal")
    rid = post(w, w.emp, f"documents/{doc}/deletion-requests", reason="tidy").json()["id"]
    post(w, w.admin, f"documents/{doc}/legal-hold", reason="Audit")
    blocked = post(w, w.admin, f"deletion-requests/{rid}/approve")
    assert blocked.status_code == 409 and "legal hold" in blocked.json()["detail"]
    assert all(exists(w, k) for k in object_keys(w, doc))  # nothing was removed


def test_a_storage_failure_deletes_nothing(cast, monkeypatch, world):
    w = cast
    doc = make_doc(w, "internal")
    rid = post(w, w.emp, f"documents/{doc}/deletion-requests", reason="tidy").json()["id"]
    from app.storage.base import StorageError

    def broken(key):
        raise StorageError("down")

    monkeypatch.setattr(world.storage, "delete", broken)
    failed = post(w, w.admin, f"deletion-requests/{rid}/approve")
    assert failed.status_code == 502
    assert life(w, w.admin, doc)["lifecycle_state"] == "approved"  # rolled back


# ---- reminders --------------------------------------------------------------------------


def test_due_list(cast):
    w = cast
    soon = make_doc(
        w, "internal", category=category_with(w, retention_days=90, review_interval_days=20)
    )
    far = make_doc(w, "internal", category=category_with(w, retention_days=300))
    with w.engine.begin() as c:
        c.exec_driver_sql(
            "UPDATE documents SET retention_until = current_date + 3 WHERE id = %s", (soon,)
        )
    items = w.client.get("/api/v1/lifecycle/due", params={"days": 30}, headers=w.admin).json()
    assert [i["document_id"] for i in items] == [soon]
    kinds = {d["kind"] for d in items[0]["due"]}
    assert kinds == {"retention_ending", "review_due"}
    wide = w.client.get("/api/v1/lifecycle/due", params={"days": 365}, headers=w.admin).json()
    assert {i["document_id"] for i in wide} == {soon, far}
    assert w.client.get("/api/v1/lifecycle/due", headers=w.emp).status_code == 403
