# ruff: noqa: F811
import itertools
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.core import ratelimit
from app.core.config import get_settings
from app.db.models import Document, DocumentAccessGrant, DocumentAssociation
from app.db.tenant_session import tenant_session
from app.services import access
from app.services.access_sql import load_viewer, visible_clause
from tests.samples import make_docx, make_pdf, make_pptx, make_xlsx
from tests.test_access import add_user, cast, make_doc, put  # noqa: F401  (fixtures)
from tests.test_rbac import auth, env  # noqa: F401  (fixtures)
from tests.test_uploads import reserve, send, world  # noqa: F401  (fixtures)

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


@pytest.fixture(autouse=True)
def fresh_limiter():
    ratelimit.search_limiter._hits.clear()


def upload_file(w, h, filename, content_type, data, **over):
    r = reserve(w, h, filename=filename, content_type=content_type, size_bytes=len(data), **over)
    assert r.status_code == 201, r.text
    done = send(w, r.json()["version_id"], data, h)
    assert done.status_code == 200, done.text
    return r.json()["document_id"]


def find(w, h, **params):
    r = w.client.get("/api/v1/search", params=params, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def ids(result):
    return [i["id"] for i in result["items"]]


@pytest.fixture
def library(cast):
    """Documents of every searchable kind, all uploaded by the owner as plain internal files."""
    w = cast
    w.doc = type("Docs", (), {})()
    w.doc.txt = upload_file(
        w,
        w.emp,
        "budget notes.txt",
        "text/plain",
        b"alpha bravo quarterly numbers",
        title="Quarterly Budget Report",
    )
    w.doc.docx = upload_file(
        w, w.emp, "plan.docx", DOCX, make_docx("charlie delta strategy"), title="Annual Plan"
    )
    w.doc.pdf = upload_file(
        w,
        w.emp,
        "invoice.pdf",
        "application/pdf",
        make_pdf("echo foxtrot payable"),
        title="Vendor Invoice",
    )
    w.doc.hindi = upload_file(
        w, w.emp, "करार.txt", "text/plain", "अनुबंध करार दस्तावेज".encode(), title="प्रकल्प अहवाल"
    )
    w.doc.xlsx = upload_file(
        w, w.emp, "sheet.xlsx", XLSX, make_xlsx("golf", "hotel"), title="Numbers"
    )
    w.doc.pptx = upload_file(
        w, w.emp, "deck.pptx", PPTX, make_pptx("india", "juliet"), title="Roadmap"
    )
    return w


# ---- finding things ---------------------------------------------------------------------


def test_search_by_title_filename_content_and_prefix(library):
    w = library
    h = w.people.stranger.h
    assert ids(find(w, h, q="quarterly")) == [w.doc.txt]  # title (and content)
    assert ids(find(w, h, q="budg")) == [w.doc.txt]  # partial word
    assert ids(find(w, h, q="bravo")) == [w.doc.txt]  # content of a text file
    assert ids(find(w, h, q="charlie")) == [w.doc.docx]  # content of a Word file
    assert ids(find(w, h, q="foxtrot")) == [w.doc.pdf]  # content of a PDF
    assert ids(find(w, h, q="hotel")) == [w.doc.xlsx]  # content of a spreadsheet
    assert ids(find(w, h, q="juliet")) == [w.doc.pptx]  # content of a presentation
    assert ids(find(w, h, q="invoice.pdf")) == [w.doc.pdf]  # file name
    assert ids(find(w, h, q="strategy annual")) == [w.doc.docx]  # all words must match
    assert find(w, h, q="nonexistentword")["total"] == 0


def test_hindi_and_marathi_search_works_with_prefixes(library):
    w = library
    h = w.people.stranger.h
    assert ids(find(w, h, q="अनुबंध")) == [w.doc.hindi]  # content word
    assert ids(find(w, h, q="अनुबं")) == [w.doc.hindi]  # prefix
    assert ids(find(w, h, q="प्रकल्प")) == [w.doc.hindi]  # Marathi title
    assert ids(find(w, h, q="अहवाल")) == [w.doc.hindi]


def test_metadata_and_tags_are_searchable(world):
    w = world
    cat = w.client.post(
        "/api/v1/categories",
        json={"name": "Invoices", "fields": [
            {"key": "vendor", "label": "Vendor", "field_type": "text", "searchable": True},
            {"key": "secret_code", "label": "Code", "field_type": "text", "searchable": False},
        ]},
        headers=w.admin,
    ).json()  # fmt: skip
    tag = w.client.post(
        "/api/v1/tags", json={"name": "Urgent", "kind": "standard"}, headers=w.admin
    ).json()
    doc = upload_file(
        w, w.emp, "scan.pdf", "application/pdf", make_pdf("nothing here"), category=cat,
        metadata={"vendor": "Zenith Traders", "secret_code": "XYZ-999"}, tag_ids=[tag["id"]],
    )  # fmt: skip
    assert ids(find(w, w.emp, q="zenith")) == [doc]
    assert ids(find(w, w.emp, q="urgent")) == [doc]
    assert find(w, w.emp, q="xyz")["total"] == 0  # fields marked not searchable stay out
    assert ids(find(w, w.emp, tag_id=tag["id"])) == [doc]


def test_filters_sorting_and_stable_pagination(cast):
    w = cast
    other = w.client.post(
        "/api/v1/categories",
        json={"name": "Reports", "parent_id": w.general["id"]},
        headers=w.admin,
    ).json()
    docs = [
        upload_file(w, w.emp, f"d{i}.txt", "text/plain", f"common word {i}".encode(), title=f"Doc {i:02d}",
                    category=other if i % 2 else None)
        for i in range(7)
    ]  # fmt: skip
    everything = find(w, w.emp, limit=100)
    assert everything["total"] == 7
    pages = [find(w, w.emp, q="common", limit=3, offset=o) for o in (0, 3, 6)]
    seen = [i for p in pages for i in ids(p)]
    assert len(seen) == 7 and len(set(seen)) == 7 and set(seen) == set(docs)  # no gaps, no repeats
    assert seen == [
        i
        for p in [find(w, w.emp, q="common", limit=3, offset=o) for o in (0, 3, 6)]
        for i in ids(p)
    ]
    by_title = [i["title"] for i in find(w, w.emp, sort="title", limit=100)["items"]]
    assert by_title == sorted(by_title)
    in_reports = find(w, w.emp, category_id=other["id"], include_subcategories=False)
    assert in_reports["total"] == 3
    with_children = find(w, w.emp, category_id=w.general["id"])
    assert with_children["total"] == 7  # sub-categories included by default
    assert find(w, w.emp, category_id=w.general["id"], include_subcategories=False)["total"] == 4
    now = datetime.now(UTC)
    assert find(w, w.emp, date_from=(now + timedelta(days=1)).isoformat())["total"] == 0
    assert (
        find(w, w.emp, date_to=(now + timedelta(days=1)).isoformat(), date_field="uploaded")[
            "total"
        ]
        == 7
    )
    assert find(w, w.emp, classification="confidential")["total"] == 0
    assert (
        find(w, w.emp, status="approved")["total"] == 7
        and find(w, w.emp, status="draft")["total"] == 0
    )
    assert find(w, w.emp, uploader_id=str(w.emp_a))["total"] == 7
    assert find(w, w.emp, owner_id=str(w.mem_emp))["total"] == 7


def test_associations_filter_and_facets(cast):
    w = cast
    make_doc(w, "internal")
    make_doc(w, "internal")
    upload_file(w, w.emp, "plain.txt", "text/plain", b"no associations")
    r = find(w, w.emp, department_id=w.dept["id"])
    assert r["total"] == 2
    assert find(w, w.emp, project_id=w.project["id"])["total"] == 2
    assert find(w, w.emp, branch_id=str(uuid.uuid4()))["total"] == 0
    facets = find(w, w.emp)["facets"]
    assert {f["value"]: f["count"] for f in facets["classification"]} == {"internal": 3}
    assert {f["value"]: f["count"] for f in facets["department"]} == {w.dept["id"]: 2}
    assert {f["value"]: f["count"] for f in facets["status"]} == {"approved": 3}


def test_bad_parameters_are_rejected(cast):
    w = cast
    for params in (
        {"limit": 101}, {"limit": 0}, {"offset": -1}, {"sort": "random"}, {"status": "weird"},
        {"q": "x" * 201}, {"q": "a b c d e f g h i"}, {"category_id": "nope"}, {"date_field": "never"},
    ):  # fmt: skip
        assert w.client.get("/api/v1/search", params=params, headers=w.emp).status_code == 422, (
            params
        )
    assert w.client.get("/api/v1/search").status_code == 401
    assert find(w, w.emp, q="&|!()'\\:*")["total"] == 0  # operators are harmless text


# ---- nothing leaks ----------------------------------------------------------------------


def test_search_never_reveals_documents_the_caller_cannot_see(cast):
    w, p = cast, cast.people
    hidden = upload_file(
        w, w.emp, "secret.txt", "text/plain", b"zebra codeword inside", title="Board Minutes",
        classification="highly_confidential",
    )  # fmt: skip
    upload_file(w, w.emp, "open.txt", "text/plain", b"public stuff", title="Open Note")
    for who in (p.stranger.h, p.fin.h, p.pm.h, w.admin_b):
        r = find(w, who, q="zebra")
        assert r["total"] == 0 and r["items"] == []
        assert find(w, who, q="board")["total"] == 0  # not by title either
    owner = find(w, w.emp, q="zebra")
    assert ids(owner) == [hidden]
    seen = find(w, p.stranger.h)
    assert seen["total"] == 1 and hidden not in ids(seen)
    for facet in seen["facets"].values():  # counts cover only visible documents
        assert sum(v["count"] for v in facet) <= 1
    assert {f["value"] for f in seen["facets"]["classification"]} == {"internal"}


def test_administrator_search_is_privileged_and_audited(cast):
    w = cast
    hidden = upload_file(
        w, w.emp, "s.txt", "text/plain", b"yankee words", classification="highly_confidential"
    )
    assert ids(find(w, w.admin, q="yankee")) == [hidden]
    log = w.client.get(
        "/api/v1/audit-events", params={"action": "document.privileged_search"}, headers=w.admin
    ).json()
    assert (
        len(log) == 1
        and log[0]["privileged"] is True
        and log[0]["details"] == {"has_query": True, "total": 1}
    )


def test_revoking_a_share_removes_the_result_immediately(cast):
    w, p = cast, cast.people
    doc = upload_file(
        w, w.emp, "s.txt", "text/plain", b"victor tango", classification="confidential"
    )
    assert find(w, p.stranger.h, q="victor")["total"] == 0
    with tenant_session(w.ta, w.engine) as s:
        grant = DocumentAccessGrant(tenant_id=w.ta, document_id=doc, grantee_membership_id=p.stranger.mid,
                                    granted_by_user_id=w.admin_a, can_view=True)  # fmt: skip
        s.add(grant)
        s.flush()
        gid = grant.id
    assert ids(find(w, p.stranger.h, q="victor")) == [doc]
    with w.engine.begin() as c:
        c.execute(
            text("UPDATE document_access_grants SET revoked_at = now() WHERE id=:i"), {"i": gid}
        )
    assert find(w, p.stranger.h, q="victor")["total"] == 0  # the index holds no permissions


def test_pending_archived_and_cross_tenant_rules(cast):
    w, p = cast, cast.people
    pending = upload_file(w, w.emp, "m.txt", "text/plain", b"whiskey memo", category=w.memos)
    assert ids(find(w, w.emp, q="whiskey")) == [pending]  # the uploader follows it
    assert find(w, p.stranger.h, q="whiskey")["total"] == 0  # pending: not for ordinary employees
    with w.engine.begin() as c:
        c.execute(
            text("UPDATE documents SET lifecycle_state='archived' WHERE id=:i"), {"i": pending}
        )
    assert ids(find(w, p.stranger.h, q="whiskey")) == [pending]  # archived stays searchable
    assert find(w, w.admin_b, q="whiskey")["total"] == 0 and find(w, w.admin_b)["total"] == 0


def test_a_role_without_metadata_rights_cannot_search(cast):
    w = cast
    assert w.client.get("/api/v1/search", headers=w.people.norole.h).status_code == 403


def test_search_is_rate_limited_per_user(cast, monkeypatch):
    w = cast
    monkeypatch.setattr(get_settings(), "SEARCH_RATE_LIMIT_PER_MINUTE", 3)
    codes = [w.client.get("/api/v1/search", headers=w.emp).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    assert (
        w.client.get("/api/v1/search", headers=w.people.stranger.h).status_code == 200
    )  # others unaffected


# ---- index health -----------------------------------------------------------------------


def test_extraction_failures_are_visible_to_administrators_and_retryable(cast):
    w = cast
    bad = upload_file(w, w.emp, "broken.pdf", "application/pdf", b"%PDF-1.4 truncated nonsense")
    upload_file(
        w, w.emp, "old.doc", "application/msword", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 40
    )
    upload_file(w, w.emp, "fine.txt", "text/plain", b"fine content")
    status = w.client.get("/api/v1/search/index/status", headers=w.admin).json()
    assert status["counts"] == {"failed": 1, "unsupported": 1, "indexed": 1}
    assert (
        status["failures"][0]["document_id"] == bad
        and status["failures"][0]["reason"] == "extract_parse_error"
    )
    assert set(status["failures"][0]) == {
        "document_id",
        "reason",
        "attempts",
        "updated_at",
    }  # no titles/content
    assert w.client.get("/api/v1/search/index/status", headers=w.emp).status_code == 403
    assert ids(find(w, w.emp, q="broken")) == [bad]  # still findable by title and file name
    assert w.client.post("/api/v1/search/index/retry", headers=w.emp).status_code == 403
    assert w.client.post("/api/v1/search/index/retry", headers=w.admin).json() == {"requeued": 1}
    ran = w.client.post("/api/v1/search/index/run", headers=w.admin).json()
    assert ran == {"indexed": 0, "failed": 1, "unsupported": 0}  # still unreadable, reported again
    log = [
        e["action"]
        for e in w.client.get("/api/v1/audit-events", params={"limit": 100}, headers=w.admin).json()
    ]
    assert "search.index_retry" in log


def test_queue_is_resumable(cast, monkeypatch):
    w = cast
    doc = upload_file(w, w.emp, "later.txt", "text/plain", b"lima content")
    with w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE document_search SET extraction_status='pending', content_tsv=NULL WHERE document_id=:i"
            ),
            {"i": doc},
        )
    assert w.client.post("/api/v1/search/index/run", headers=w.admin).json()["indexed"] == 1
    assert ids(find(w, w.emp, q="lima")) == [doc]


# ---- the SQL filter and the policy engine must agree ------------------------------------


def test_sql_visibility_equals_the_policy_engine_for_every_viewer(cast):
    w, p = cast, cast.people
    fin_x = add_user(w, "finx@x.test")
    pmem_x = add_user(w, "pmemx@x.test")
    grantee = {k: add_user(w, f"g-{k}@x.test") for k in ("ok", "expired", "revoked")}
    w.client.put(
        f"/api/v1/employees/{fin_x.mid}/profile",
        json={"full_name": "X", "department_id": w.dept["id"], "employment_status": "exited"},
        headers=w.admin,
    )
    w.client.put(
        f"/api/v1/projects/{w.project['id']}/members/{pmem_x.mid}", json={}, headers=w.admin
    )
    with w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE project_memberships SET ends_on = current_date - 1 WHERE membership_id=:m"
            ),
            {"m": pmem_x.mid},
        )

    with tenant_session(w.ta, w.engine) as s:
        category_id = uuid.UUID(w.general["id"])
        created = []
        combos = itertools.product(
            ("public", "internal", "confidential", "highly_confidential"),
            ("approved", "submitted", "archived"),
            ((), ("department",), ("department", "project")),
            (("emp", "emp"), ("dm", "emp"), ("dm", "stranger")),  # (owner, uploader)
        )  # fmt: skip
        who = {
            "emp": (w.mem_emp, w.emp_a),
            "dm": (p.dm.mid, p.dm.uid),
            "stranger": (p.stranger.mid, p.stranger.uid),
        }
        for i, (cls, state, dims, (owner, uploader)) in enumerate(combos):
            d = Document(
                tenant_id=w.ta, title=f"matrix {i}", category_id=category_id, category_version_number=1,
                classification=cls, lifecycle_state=state, owner_membership_id=who[owner][0],
                created_by_user_id=who[uploader][1], current_version_number=1,
            )  # fmt: skip
            s.add(d)
            s.flush()
            refs = {"department": uuid.UUID(w.dept["id"]), "project": uuid.UUID(w.project["id"])}
            for dim in dims:
                s.add(
                    DocumentAssociation(
                        tenant_id=w.ta, document_id=d.id, dimension=dim, ref_id=refs[dim]
                    )
                )
            created.append(d)
        s.flush()
        now = datetime.now(UTC)
        for n, d in enumerate(created):
            if n % 3:
                continue
            for key, kw in (
                ("ok", {}),
                ("expired", {"expires_at": now - timedelta(hours=1)}),
                ("revoked", {"revoked_at": now}),
            ):
                s.add(DocumentAccessGrant(tenant_id=w.ta, document_id=d.id, grantee_membership_id=grantee[key].mid,
                                          granted_by_user_id=w.admin_a, can_view=True, **kw))  # fmt: skip
        doc_ids = [d.id for d in created]

    viewers = {
        "owner": w.emp, "stranger": p.stranger.h, "dm": p.dm.h, "fin": p.fin.h, "pm": p.pm.h,
        "pmem": p.pmem.h, "rev": p.rev.h, "norole": p.norole.h, "admin": w.admin,
        "fin_exited": fin_x.h, "pmem_ended": pmem_x.h, "g_ok": grantee["ok"].h,
        "g_expired": grantee["expired"].h, "g_revoked": grantee["revoked"].h,
    }  # fmt: skip
    users = {
        "owner": w.emp_a, "stranger": p.stranger.uid, "dm": p.dm.uid, "fin": p.fin.uid, "pm": p.pm.uid,
        "pmem": p.pmem.uid, "rev": p.rev.uid, "norole": p.norole.uid, "admin": w.admin_a,
        "fin_exited": fin_x.uid, "pmem_ended": pmem_x.uid, "g_ok": grantee["ok"].uid,
        "g_expired": grantee["expired"].uid, "g_revoked": grantee["revoked"].uid,
    }  # fmt: skip
    mismatches = []
    with tenant_session(w.ta, w.engine) as s:
        docs = {d.id: d for d in s.scalars(select(Document).where(Document.id.in_(doc_ids)))}
        for name, user_id in users.items():
            viewer = load_viewer(s, w.ta, user_id)
            by_sql = {
                i
                for i in s.scalars(
                    select(Document.id).where(Document.id.in_(doc_ids), visible_clause(viewer))
                )
            }
            by_policy = {
                i
                for i, d in docs.items()
                if access.decide(s, w.ta, user_id, d, "view_metadata").allowed
            }
            if by_sql != by_policy:
                mismatches.append((name, len(by_sql ^ by_policy)))
    assert mismatches == []
    # sanity: the matrix really exercised both outcomes for the interesting viewers
    sizes = {}
    with tenant_session(w.ta, w.engine) as s:
        for name in ("stranger", "dm", "g_ok", "g_expired", "admin"):
            sizes[name] = len(
                set(
                    s.scalars(
                        select(Document.id).where(
                            Document.id.in_(doc_ids),
                            visible_clause(load_viewer(s, w.ta, users[name])),
                        )
                    )
                )
            )
    assert 0 < sizes["stranger"] < sizes["dm"] < sizes["admin"] == len(doc_ids)
    assert (
        sizes["g_ok"] > sizes["g_expired"]
    )  # a valid share adds documents; an expired one adds none
    # and the HTTP search agrees with the same sets
    for name in ("stranger", "dm", "g_ok", "admin", "norole"):
        r = w.client.get("/api/v1/search", params={"limit": 1}, headers=viewers[name])
        if name == "norole":
            assert r.status_code == 403
        else:
            assert r.json()["total"] >= sizes[name]
