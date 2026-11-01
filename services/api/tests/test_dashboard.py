# ruff: noqa: F811
from tests.test_access import cast, make_doc  # noqa: F401  (fixtures)
from tests.test_rbac import auth, env  # noqa: F401
from tests.test_uploads import world  # noqa: F401


def dash(w, h):
    r = w.client.get("/api/v1/dashboard", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_counts_follow_what_each_person_may_see(cast):
    w, p = cast, cast.people
    make_doc(w, "internal")
    make_doc(w, "confidential")
    make_doc(w, "highly_confidential")
    owner = dash(w, w.emp)
    stranger = dash(w, p.stranger.h)
    assert owner["stats"]["documents"] == 3
    # a stranger sees the internal one only: no hint that the others exist
    assert stranger["stats"]["documents"] == 1
    assert {c["value"]: c["count"] for c in stranger["by_classification"]} == {"internal": 1}
    assert [d["classification"] for d in stranger["recent_documents"]] == ["internal"]
    assert stranger["stats"]["storage_bytes"] < owner["stats"]["storage_bytes"]


def test_upload_chart_covers_thirty_days_ending_today(cast):
    w = cast
    make_doc(w, "internal")
    days = dash(w, w.emp)["uploads_by_day"]
    assert len(days) == 30
    assert days == sorted(days, key=lambda d: d["date"])
    assert days[-1]["count"] == 1 and sum(d["count"] for d in days) == 1


def test_activity_is_only_for_people_who_may_read_the_audit_log(cast):
    w, p = cast, cast.people
    make_doc(w, "internal")
    assert dash(w, p.stranger.h)["activity"] is None
    admin = dash(w, w.admin)["activity"]
    assert admin and {"action", "outcome", "occurred_at", "actor"} <= set(admin[0])


def test_review_queue_counts_only_my_reviews(cast):
    w, p = cast, cast.people
    r = w.client.get("/api/v1/dashboard", headers=p.rev.h).json()
    assert r["stats"]["pending_reviews"] == 0 and r["approvals_queue"] == []


def test_needs_a_signed_in_person_who_can_view_documents(cast):
    w, p = cast, cast.people
    assert w.client.get("/api/v1/dashboard").status_code == 401
    assert w.client.get("/api/v1/dashboard", headers=p.norole.h).status_code == 403


def test_other_organizations_see_nothing_of_this_one(cast):
    w = cast
    make_doc(w, "internal")
    assert dash(w, w.admin_b)["stats"]["documents"] == 0
