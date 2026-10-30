# ruff: noqa: F811
from datetime import UTC, datetime, timedelta

from tests.test_access import FORBIDDEN, NO, OK, add_user, can, cast, make_doc  # noqa: F401
from tests.test_rbac import auth, env  # noqa: F401
from tests.test_uploads import world  # noqa: F401


def url(doc, suffix=""):
    return f"/api/v1/documents/{doc}/shares{suffix}"


def share(w, h, doc, who, **body):
    return w.client.post(url(doc), json={"grantee_membership_id": str(who.mid), **body}, headers=h)


def future(hours=24):
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


def test_share_view_then_download_then_revoke(cast):
    w, p = cast, cast.people
    doc = make_doc(w, "confidential")
    assert can(w, p.stranger, doc) == (NO, NO, NO)
    r = share(w, w.emp, doc, p.stranger)
    assert r.status_code == 201 and r.json()["can_view"] and not r.json()["can_download"]
    assert can(w, p.stranger, doc) == (OK, OK, NO)  # seeing is not downloading
    again = share(w, w.emp, doc, p.stranger, can_download=True, expires_at=future())
    assert again.status_code == 200 and again.json()["can_download"]
    assert can(w, p.stranger, doc) == (OK, OK, OK)
    listed = w.client.get(url(doc), headers=w.emp).json()
    assert [(s["grantee_membership_id"], s["can_download"]) for s in listed] == [
        (str(p.stranger.mid), True)
    ]
    gone = w.client.delete(url(doc, f"/{p.stranger.mid}"), headers=w.emp)
    assert gone.status_code == 200 and gone.json()["revoked_at"]
    assert can(w, p.stranger, doc) == (NO, NO, NO)
    assert w.client.get(url(doc), headers=w.emp).json() == []
    assert len(w.client.get(url(doc) + "?history=true", headers=w.emp).json()) == 1
    assert w.client.delete(url(doc, f"/{p.stranger.mid}"), headers=w.emp).status_code == 404
    assert share(w, w.emp, doc, p.stranger).status_code == 201  # a new share after revoking
    log = {
        e["action"]
        for e in w.client.get("/api/v1/audit-events", params={"limit": 100}, headers=w.admin).json()
    }
    assert {"share.created", "share.updated", "share.revoked"} <= log


def test_lists_with_me_and_by_me(cast):
    w, p = cast, cast.people
    doc = make_doc(w, "confidential")
    share(w, w.emp, doc, p.stranger, can_download=True)
    mine = w.client.get("/api/v1/shares/with-me", headers=p.stranger.h).json()
    assert [(m["document_id"], m["can_download"]) for m in mine] == [(doc, True)]
    assert w.client.get("/api/v1/shares/with-me", headers=p.fin.h).json() == []
    by = w.client.get("/api/v1/shares/by-me", headers=w.emp).json()
    assert [b["document_id"] for b in by] == [doc] and by[0]["grantee_name"] is None
    w.client.delete(url(doc, f"/{p.stranger.mid}"), headers=w.emp)
    assert w.client.get("/api/v1/shares/with-me", headers=p.stranger.h).json() == []
    assert w.client.get("/api/v1/shares/by-me", headers=w.emp).json() == []


def test_expiry(cast):
    w, p = cast, cast.people
    doc = make_doc(w, "confidential")
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    assert share(w, w.emp, doc, p.stranger, expires_at=past).status_code == 422
    assert share(w, w.emp, doc, p.stranger, expires_at="2099-01-01T00:00:00").status_code == 422
    assert share(w, w.emp, doc, p.stranger, expires_at=future(1)).status_code == 201
    with w.engine.begin() as c:
        c.exec_driver_sql(
            "UPDATE document_access_grants SET expires_at = now() - interval '1 minute'"
        )
    assert can(w, p.stranger, doc) == (NO, NO, NO)
    assert w.client.get("/api/v1/shares/with-me", headers=p.stranger.h).json() == []
    assert w.client.get(url(doc), headers=w.emp).json() == []


def test_who_may_share(cast):
    w, p = cast, cast.people
    doc = make_doc(w, "confidential")
    assert (
        share(w, p.stranger.h if hasattr(p.stranger, "h") else None, doc, p.fin).status_code == 404
    )  # cannot see it
    share(w, w.emp, doc, p.stranger)
    assert share(w, p.stranger.h, doc, p.norole).status_code == 404  # recipients cannot re-share
    assert w.client.get(url(doc), headers=p.stranger.h).status_code == 404
    assert share(w, p.norole.h, doc, p.fin).status_code == 403  # no share permission
    assert share(w, p.rev.h, doc, p.fin).status_code == 403  # reviewer role lacks it
    by_admin = share(w, w.admin, doc, p.pmem)
    assert by_admin.status_code == 201  # privileged, flagged
    flagged = w.client.get(
        "/api/v1/audit-events", params={"action": "share.created"}, headers=w.admin
    ).json()
    assert any(e["privileged"] for e in flagged)
    assert share(w, w.admin_b, doc, p.fin).status_code in (403, 404)
    denied = w.client.get(
        "/api/v1/audit-events", params={"action": "document.access_denied"}, headers=w.admin
    ).json()
    assert any(e["details"]["access"] == "share" for e in denied)


def test_highly_confidential_only_the_owner_shares(cast):
    w, p = cast, cast.people
    doc = make_doc(w, "highly_confidential", h=p.stranger.h, owner_membership_id=str(w.mem_emp))
    assert share(w, p.stranger.h, doc, p.fin).status_code == 404  # uploader, not owner
    assert share(w, w.emp, doc, p.fin).status_code == 201


def test_recipient_rules(cast):
    w, p = cast, cast.people
    doc = make_doc(w, "confidential")
    assert share(w, w.emp, doc, p.stranger, can_view=False).status_code == 422  # no right chosen
    assert share(w, w.emp, doc, p.norole).status_code == 422  # role gives no access at all
    assert share(w, w.emp, doc, p.rev, can_download=True).status_code == 422  # role cannot download
    assert share(w, w.emp, doc, p.rev).status_code == 201
    me = type("M", (), {"mid": w.mem_emp})
    assert share(w, w.emp, doc, me).status_code == 422  # yourself / the owner
    ghost = type("M", (), {"mid": "00000000-0000-0000-0000-000000000000"})
    assert share(w, w.emp, doc, ghost).status_code == 404
    other_org = type("M", (), {"mid": w.mem_admin_b})
    assert share(w, w.emp, doc, other_org).status_code == 404
    assert (
        w.client.post(
            url(doc), json={"grantee_membership_id": str(p.fin.mid), "x": 1}, headers=w.emp
        ).status_code
        == 422
    )


def test_unreleased_documents_cannot_be_shared(cast):
    w, p = cast, cast.people
    doc = make_doc(w, "internal", category=w.memos)  # needs approval: still submitted
    r = share(w, w.emp, doc, p.stranger)
    assert r.status_code == 409 and "released" in r.json()["detail"]


def test_revoking_reaches_old_versions_and_other_organizations_are_blind(cast):
    w, p = cast, cast.people
    doc = make_doc(w, "confidential")
    share(w, w.emp, doc, p.stranger, can_download=True)
    assert (
        w.client.get(
            f"/api/v1/documents/{doc}/versions/1/download-url", headers=p.stranger.h
        ).status_code
        == 200
    )
    w.client.delete(url(doc, f"/{p.stranger.mid}"), headers=w.emp)
    assert (
        w.client.get(
            f"/api/v1/documents/{doc}/versions/1/download-url", headers=p.stranger.h
        ).status_code
        == 404
    )
    assert w.client.get("/api/v1/shares/with-me", headers=w.admin_b).json() == []
