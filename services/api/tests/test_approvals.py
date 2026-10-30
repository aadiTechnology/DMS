# ruff: noqa: F811
import uuid
from urllib.parse import urlparse

import pytest

from app.db.tenant_session import tenant_session
from app.services import rbac
from tests.test_access import add_user, cast  # noqa: F401  (fixtures)
from tests.test_rbac import auth, env  # noqa: F401
from tests.test_uploads import reserve, send, world  # noqa: F401  (fixtures)


@pytest.fixture(autouse=True)
def managers_can_approve(cast):
    w = cast
    with tenant_session(w.ta, w.engine) as s:
        for who in (w.people.dm, w.people.pm):
            rbac.assign_role(s, w.ta, w.admin_a, who.mid, w.roles_a["department_manager"])


@pytest.fixture(autouse=True)
def serve_local_files(monkeypatch, world):
    monkeypatch.setattr("app.api.dev_storage.get_storage", lambda: world.storage)
    monkeypatch.setattr("app.api.versions.get_storage", lambda: world.storage)


def memo(w, h=None, data=b"memo text", category=None, name="m.txt", **over):
    r = reserve(
        w,
        h or w.emp,
        category=category or w.memos,
        filename=name,
        content_type="text/plain",
        size_bytes=len(data),
        **over,
    )
    assert r.status_code == 201, r.text
    assert send(w, r.json()["version_id"], data, h or w.emp).status_code == 200
    return r.json()["document_id"]


def request_of(w, h, doc, index=0):
    r = w.client.get(f"/api/v1/documents/{doc}/approvals", headers=h)
    assert r.status_code == 200, r.text
    return r.json()[index]


def act(w, h, rid, action, **body):
    return w.client.post(f"/api/v1/approvals/{rid}/{action}", json=body, headers=h)


def reach(w, h, doc, n=1, kind="preview"):
    """Status of a read: 404 means no access; 415 means allowed but a text file has no preview."""
    return w.client.get(f"/api/v1/documents/{doc}/versions/{n}/{kind}-url", headers=h).status_code


def doc_state(w, h, doc):
    return w.client.get(f"/api/v1/documents/{doc}", headers=h).json()


def download(w, h, doc, n=1, kind="download"):
    r = w.client.get(f"/api/v1/documents/{doc}/versions/{n}/{kind}-url", headers=h)
    if r.status_code != 200:
        return None
    return w.client.get(urlparse(r.json()["url"]).path).content


def steps_category(w, name, steps, **extra):
    r = w.client.post(
        "/api/v1/categories",
        json={
            "name": name,
            "policy": {"approval_required": True, "approval_steps": steps},
            **extra,
        },
        headers=w.admin,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---- the default single step ------------------------------------------------------------


def test_default_review_flow_end_to_end(cast):
    w, p = cast, cast.people
    doc = memo(w, data=b"quarterly memo text")
    d = doc_state(w, w.emp, doc)
    assert d["lifecycle_state"] == "submitted" and d["versions"][0]["review_status"] == "pending"
    req = request_of(w, w.emp, doc)
    rid = req["id"]
    assert (req["status"], req["current_step"], req["total_steps"]) == ("pending", 1, 1)
    reviewers = {a["membership_id"] for a in req["assignments"]}
    assert (
        str(p.rev.mid) in reviewers
        and str(p.dm.mid) in reviewers
        and str(w.mem_emp) not in reviewers
    )
    assert str(p.stranger.mid) not in reviewers  # plain employees cannot review

    queue = w.client.get("/api/v1/approvals/queue", headers=p.rev.h).json()
    assert [(q["id"], q["title"]) for q in queue] == [(rid, "m")]
    assert (
        w.client.get("/api/v1/approvals/queue", headers=w.emp).json() == []
    )  # not your own submission
    assert w.client.get("/api/v1/approvals/queue", headers=p.stranger.h).json() == []

    # reviewers can open the pending version; ordinary employees cannot
    assert reach(w, p.rev.h, doc) == 415
    assert download(w, p.stranger.h, doc) is None
    assert w.client.get(f"/api/v1/documents/{doc}", headers=p.stranger.h).status_code == 404
    assert (
        w.client.get("/api/v1/search", params={"q": "quarterly"}, headers=p.rev.h).json()["total"]
        == 1
    )
    assert (
        w.client.get("/api/v1/search", params={"q": "quarterly"}, headers=p.stranger.h).json()[
            "total"
        ]
        == 0
    )
    assert w.client.get(f"/api/v1/approvals/{rid}", headers=p.stranger.h).status_code == 404

    done = act(w, p.rev.h, rid, "approve", comment="Looks good")
    assert (
        done.status_code == 200
        and done.json()["status"] == "approved"
        and done.json()["can_decide"] is False
    )
    d = doc_state(w, p.stranger.h, doc)  # released: ordinary employees can now see it
    assert d["lifecycle_state"] == "approved" and d["versions"][0]["review_status"] == "approved"
    assert download(w, p.stranger.h, doc) == b"quarterly memo text"
    assert w.client.get("/api/v1/approvals/queue", headers=p.rev.h).json() == []
    actions = [(e["action"], e["comment"]) for e in done.json()["events"]]
    assert actions == [("submitted", None), ("step_started", None), ("approved", "Looks good")]

    again = act(w, p.rev.h, rid, "approve")  # a repeated click changes nothing
    assert again.status_code == 200 and len(again.json()["events"]) == 3
    other = act(w, p.dm.h, rid, "approve")  # someone else after completion
    assert other.status_code == 409
    log = [
        e["action"]
        for e in w.client.get("/api/v1/audit-events", params={"limit": 200}, headers=w.admin).json()
    ]
    assert {
        "approval.submitted",
        "approval.step_started",
        "approval.approved",
        "approval.completed",
    } <= set(log)


def test_nobody_decides_their_own_submission(cast):
    w, p = cast, cast.people
    doc = memo(w, h=p.rev.h)  # the reviewer submits it
    rid = request_of(w, p.rev.h, doc)["id"]
    own = act(w, p.rev.h, rid, "approve")
    assert own.status_code == 403 and "own submission" in own.json()["detail"]
    assert w.client.get("/api/v1/approvals/queue", headers=p.rev.h).json() == []
    admin_doc = memo(w, h=w.admin)  # an administrator submits
    admin_rid = request_of(w, w.admin, admin_doc)["id"]
    assert act(w, w.admin, admin_rid, "approve").status_code == 403  # privilege does not lift this
    assert act(w, p.dm.h, admin_rid, "approve").status_code == 200  # but a colleague can


def test_rejection_needs_a_reason_and_resubmission_keeps_history(cast):
    w, p = cast, cast.people
    doc = memo(w)
    first = request_of(w, w.emp, doc)["id"]
    assert act(w, p.rev.h, first, "reject").status_code == 422
    assert act(w, p.rev.h, first, "reject", reason="   ").status_code == 422
    rejected = act(w, p.rev.h, first, "reject", reason="Missing the budget table")
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    d = doc_state(w, w.emp, doc)
    assert d["lifecycle_state"] == "rejected" and d["versions"][0]["review_status"] == "rejected"
    assert download(w, p.stranger.h, doc) is None
    assert (
        act(w, p.rev.h, first, "reject", reason="Missing the budget table").status_code == 200
    )  # repeat is harmless
    assert act(w, p.dm.h, first, "approve").status_code == 409  # already decided

    assert (
        w.client.post(f"/api/v1/documents/{doc}/resubmit", headers=p.stranger.h).status_code == 404
    )
    edit = w.client.patch(
        f"/api/v1/documents/{doc}",
        json={"row_version": d["row_version"], "title": "Memo with budget"},
        headers=w.emp,
    )
    assert edit.status_code == 200
    again = w.client.post(f"/api/v1/documents/{doc}/resubmit", headers=w.emp)
    assert again.status_code == 201 and again.json()["resubmission_of"] == first
    assert doc_state(w, w.emp, doc)["lifecycle_state"] == "submitted"
    assert (
        w.client.post(f"/api/v1/documents/{doc}/resubmit", headers=w.emp).status_code == 409
    )  # nothing rejected now
    assert act(w, p.dm.h, again.json()["id"], "approve", comment="Fixed").status_code == 200
    history = w.client.get(f"/api/v1/documents/{doc}/approvals", headers=w.emp).json()
    assert [(h["status"], h["resubmission_of"] is not None) for h in history] == [
        ("approved", True),
        ("rejected", False),
    ]
    old = next(h for h in history if h["status"] == "rejected")
    assert ("rejected", "Missing the budget table") in [
        (e["action"], e["comment"]) for e in old["events"]
    ]
    assert doc_state(w, p.stranger.h, doc)["lifecycle_state"] == "approved"


def test_comments(cast):
    w, p = cast, cast.people
    rid = request_of(w, w.emp, memo(w))["id"]
    assert act(w, p.rev.h, rid, "comments", comment="Please attach the PO").status_code == 201
    assert act(w, w.emp, rid, "comments", comment="PO attached in v2").status_code == 201
    assert act(w, p.stranger.h, rid, "comments", comment="hello").status_code == 404
    assert act(w, p.rev.h, rid, "comments", comment="  ").status_code == 422
    events = w.client.get(f"/api/v1/approvals/{rid}", headers=w.emp).json()["events"]
    assert [e["comment"] for e in events if e["action"] == "commented"] == [
        "Please attach the PO",
        "PO attached in v2",
    ]


# ---- steps ------------------------------------------------------------------------------


def test_two_step_review_by_role_then_department_manager(cast):
    w, p = cast, cast.people
    cat = steps_category(
        w,
        "Contracts2",
        [{"type": "role", "ref": str(w.roles_a["reviewer"])}, {"type": "department_manager"}],
    )
    doc = memo(w, category=cat, associations={"department": [w.dept["id"]]})
    req = request_of(w, w.emp, doc)
    rid = req["id"]
    step1 = {a["membership_id"] for a in req["assignments"] if a["step_number"] == 1}
    assert step1 == {str(p.rev.mid)}  # only holders of the reviewer role
    assert act(w, p.dm.h, rid, "approve").status_code == 404  # not their step yet
    first = act(w, p.rev.h, rid, "approve", comment="Step one ok")
    assert (
        first.status_code == 200
        and first.json()["status"] == "pending"
        and first.json()["current_step"] == 2
    )
    assert doc_state(w, w.emp, doc)["lifecycle_state"] == "under_review"
    step2 = {a["membership_id"] for a in first.json()["assignments"] if a["step_number"] == 2}
    assert step2 == {str(p.dm.mid)}  # the manager of the associated department
    assert w.client.get("/api/v1/approvals/queue", headers=p.rev.h).json() == []
    assert len(w.client.get("/api/v1/approvals/queue", headers=p.dm.h).json()) == 1
    assert download(w, p.stranger.h, doc) is None  # still not released
    assert (
        act(w, p.rev.h, rid, "approve").status_code == 200
    )  # the same person again: harmless repeat
    final = act(w, p.dm.h, rid, "approve")
    assert final.json()["status"] == "approved"
    assert [e["action"] for e in final.json()["events"]].count("approved") == 2
    assert download(w, p.stranger.h, doc) == b"memo text"


def test_a_step_with_nobody_eligible_waits_for_an_administrator(cast):
    w, p = cast, cast.people
    cat = steps_category(w, "NoManager", [{"type": "department_manager"}])
    doc = memo(w, category=cat)  # no department association, so no manager to assign
    req = request_of(w, w.emp, doc)
    assert req["assignments"] == []
    assert act(w, p.dm.h, req["id"], "approve").status_code == 404
    assert w.client.get("/api/v1/approvals/pending", headers=p.dm.h).status_code == 403
    pending = w.client.get("/api/v1/approvals/pending", headers=w.admin).json()
    assert [(i["id"], i["reviewers_on_step"]) for i in pending] == [(req["id"], 0)]
    done = act(w, w.admin, req["id"], "approve", comment="Covering for the missing manager")
    assert done.status_code == 200
    approved = next(e for e in done.json()["events"] if e["action"] == "approved")
    assert approved["privileged"] is True
    priv = w.client.get(
        "/api/v1/audit-events", params={"action": "approval.approved"}, headers=w.admin
    ).json()
    assert (
        priv[0]["privileged"] is True and priv[0]["details"]["basis"] == "administrator_privilege"
    )


def test_step_configuration_is_validated(cast):
    w = cast

    def make(steps, approval=True):
        return w.client.post(
            "/api/v1/categories",
            json={
                "name": f"C{uuid.uuid4().hex[:6]}",
                "policy": {"approval_required": approval, "approval_steps": steps},
            },
            headers=w.admin,
        )

    assert make([{"type": "user", "ref": str(w.mem_emp)}]).status_code == 201
    assert (
        make([{"type": "user", "ref": str(w.mem_admin_b)}]).status_code == 422
    )  # other organization
    assert make([{"type": "role", "ref": str(w.roles_b["reviewer"])}]).status_code == 422
    assert make([{"type": "department_manager", "ref": str(w.mem_emp)}]).status_code == 422
    assert make([{"type": "user"}]).status_code == 422
    assert make([{"type": "ceo"}]).status_code == 422
    assert (
        make([{"type": "role", "ref": str(w.roles_a["reviewer"])}], approval=False).status_code
        == 422
    )
    assert make([{"type": "role", "ref": str(w.roles_a["reviewer"])}] * 6).status_code == 422
    cat = make([{"type": "role", "ref": str(w.roles_a["reviewer"])}]).json()
    assert cat["version"]["approval_steps"] == [{"type": "role", "ref": str(w.roles_a["reviewer"])}]


# ---- later versions ---------------------------------------------------------------------


def test_second_version_flow(cast):
    w, p = cast, cast.people
    doc = memo(w, data=b"alphaword first draft")
    assert act(w, p.rev.h, request_of(w, w.emp, doc)["id"], "approve").status_code == 200
    data = b"betaword second draft"
    r = w.client.post(
        f"/api/v1/documents/{doc}/versions/uploads",
        json={
            "filename": "m.txt",
            "content_type": "text/plain",
            "size_bytes": len(data),
            "based_on_version": 1,
        },
        headers=w.emp,
    )
    assert r.status_code == 201
    assert send(w, r.json()["version_id"], data, w.emp).status_code == 200
    reqs = w.client.get(f"/api/v1/documents/{doc}/approvals", headers=w.emp).json()
    rid = reqs[0]["id"]
    assert (reqs[0]["version_number"], reqs[0]["status"]) == (2, "pending")
    assert doc_state(w, w.emp, doc)["current_version_number"] == 1
    assert download(w, p.stranger.h, doc, 1) == b"alphaword first draft"
    assert download(w, p.stranger.h, doc, 2) is None
    assert reach(w, p.rev.h, doc, 2) == 415  # the reviewer can open the version under review
    assert reach(w, p.rev.h, doc, 1) == 415
    w.client.post("/api/v1/search/index/run", headers=w.admin)
    hit = lambda who, q: w.client.get("/api/v1/search", params={"q": q}, headers=who).json()[
        "total"
    ]
    assert hit(p.stranger.h, "alphaword") == 1 and hit(p.stranger.h, "betaword") == 0
    assert act(w, p.rev.h, rid, "approve").status_code == 200
    assert doc_state(w, w.emp, doc)["current_version_number"] == 2
    assert download(w, p.stranger.h, doc, 2) == data
    w.client.post("/api/v1/search/index/run", headers=w.admin)
    assert (
        hit(p.stranger.h, "betaword") == 1 and hit(p.stranger.h, "alphaword") == 0
    )  # search follows the release


def test_rejected_second_version_leaves_the_published_one_in_place(cast):
    w, p = cast, cast.people
    doc = memo(w, data=b"stable first")
    assert act(w, p.rev.h, request_of(w, w.emp, doc)["id"], "approve").status_code == 200
    data = b"risky second"
    r = w.client.post(
        f"/api/v1/documents/{doc}/versions/uploads",
        json={
            "filename": "m.txt",
            "content_type": "text/plain",
            "size_bytes": len(data),
            "based_on_version": 1,
        },
        headers=w.emp,
    )
    send(w, r.json()["version_id"], data, w.emp)
    rid = request_of(w, w.emp, doc)["id"]
    assert act(w, p.dm.h, rid, "reject", reason="Not ready").status_code == 200
    d = doc_state(w, w.emp, doc)
    assert d["lifecycle_state"] == "approved" and d["current_version_number"] == 1
    assert [(v["version_number"], v["review_status"]) for v in d["versions"]] == [
        (1, "approved"),
        (2, "rejected"),
    ]
    assert download(w, p.stranger.h, doc, 1) == b"stable first"
    third = w.client.post(
        f"/api/v1/documents/{doc}/versions/uploads",
        json={
            "filename": "m.txt",
            "content_type": "text/plain",
            "size_bytes": 5,
            "based_on_version": 2,
        },
        headers=w.emp,
    )
    assert third.status_code == 201  # a rejected version no longer blocks new uploads


# ---- who may act ------------------------------------------------------------------------


def test_only_assigned_reviewers_with_the_right_permission_can_decide(cast):
    w, p = cast, cast.people
    rid = request_of(w, w.emp, memo(w))["id"]
    assert (
        act(w, p.stranger.h, rid, "approve").status_code == 403
    )  # employee role cannot approve at all
    assert act(w, p.norole.h, rid, "approve").status_code == 403
    assert act(w, w.admin_b, rid, "approve").status_code == 404  # other organization
    assert w.client.post(f"/api/v1/approvals/{rid}/approve").status_code == 401
    assert act(w, p.stranger.h, str(uuid.uuid4()), "approve").status_code == 404
    assert act(w, p.rev.h, str(uuid.uuid4()), "approve").status_code == 404
    denied = w.client.get(
        "/api/v1/audit-events", params={"action": "approval.access_denied"}, headers=w.admin
    ).json()
    assert {e["details"]["reason"] for e in denied} >= {"role_lacks_permission", "missing"}
    unassigned = steps_category(w, "OnlyRev", [{"type": "role", "ref": str(w.roles_a["reviewer"])}])
    rid2 = request_of(w, w.emp, memo(w, category=unassigned))["id"]
    pm_try = act(w, p.pm.h, rid2, "approve")  # holds the approve right but is not assigned here
    assert pm_try.status_code == 404
    log = w.client.get(
        "/api/v1/audit-events", params={"action": "approval.access_denied"}, headers=w.admin
    ).json()
    assert any(e["details"]["reason"] == "not_assigned" for e in log)


def test_two_reviewers_cannot_both_complete_the_same_step(cast):
    w, p = cast, cast.people
    rid = request_of(w, w.emp, memo(w))["id"]
    assert act(w, p.rev.h, rid, "approve").status_code == 200
    late = act(w, p.dm.h, rid, "reject", reason="too late")
    assert late.status_code == 409 and "approved" in late.json()["detail"]


def test_review_history_is_private_to_those_involved(cast):
    w, p = cast, cast.people
    doc = memo(w)
    rid = request_of(w, w.emp, doc)["id"]
    assert w.client.get(f"/api/v1/approvals/{rid}", headers=p.rev.h).status_code == 200  # assigned
    assert (
        w.client.get(f"/api/v1/approvals/{rid}", headers=w.admin).status_code == 200
    )  # privileged
    assert w.client.get(f"/api/v1/approvals/{rid}", headers=p.stranger.h).status_code == 404
    assert (
        w.client.get(f"/api/v1/documents/{doc}/approvals", headers=p.stranger.h).status_code == 404
    )
    act(w, p.rev.h, rid, "approve")
    # once published a stranger may open the document but the review discussion stays private
    assert (
        w.client.get(f"/api/v1/documents/{doc}/approvals", headers=p.stranger.h).status_code == 404
    )
