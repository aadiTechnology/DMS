# ruff: noqa: F811
import pytest

from tests.test_access import add_user, cast  # noqa: F401  (fixtures)
from tests.test_rbac import auth, env  # noqa: F401
from tests.test_uploads import world  # noqa: F401


def profile(w, who, name, **extra):
    r = w.client.put(
        f"/api/v1/employees/{who.mid}/profile", json={"full_name": name, **extra}, headers=w.admin
    )
    assert r.status_code == 200, r.text


@pytest.fixture
def people(cast):
    w, p = cast, cast.people
    for who, name in (
        (p.stranger, "Anita Desai"),
        (p.dm, "Rohan Deshmukh"),
        (p.fin, "Anil Kapoor"),
        (p.rev, "Meera Joshi"),
    ):
        profile(w, who, name)
    profile(w, p.pm, "100% Real_Name")
    return w


def find(w, h, **params):
    r = w.client.get("/api/v1/directory", params=params, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_colleagues_are_found_by_part_of_the_name(people):
    w = people
    assert {x["full_name"] for x in find(w, w.emp, q="ani")} == {"Anita Desai", "Anil Kapoor"}
    assert [x["full_name"] for x in find(w, w.emp, q="ANIL")] == ["Anil Kapoor"]
    names = [x["full_name"] for x in find(w, w.emp)]
    assert names == sorted(names) and "Rohan Deshmukh" in names


def test_only_name_and_department_are_exposed(people):
    w, p = people, people.people
    profile(w, p.dm, "Rohan Deshmukh", department_id=w.dept["id"])
    row = find(w, w.emp, q="rohan")[0]
    assert (
        set(row) == {"membership_id", "full_name", "department"} and row["department"] == "Finance"
    )


def test_you_and_people_who_left_are_not_listed(people):
    w, p = people, people.people
    profile(w, p.owner, "Sameer Patil")
    assert all(x["full_name"] != "Sameer Patil" for x in find(w, w.emp))  # not yourself
    profile(w, p.stranger, "Anita Desai", employment_status="exited")
    assert all(x["full_name"] != "Anita Desai" for x in find(w, w.emp))


def test_wildcards_in_the_search_text_are_literal(people):
    w = people
    assert [x["full_name"] for x in find(w, w.emp, q="100%")] == ["100% Real_Name"]
    assert find(w, w.emp, q="%") == [
        {
            "membership_id": find(w, w.emp, q="100%")[0]["membership_id"],
            "full_name": "100% Real_Name",
            "department": None,
        }
    ]
    assert find(w, w.emp, q="_") != [] and all("_" in x["full_name"] for x in find(w, w.emp, q="_"))


def test_limit_is_applied_and_validated(people):
    w = people
    assert len(find(w, w.emp, limit=2)) == 2
    assert (
        w.client.get("/api/v1/directory", params={"limit": 500}, headers=w.emp).status_code == 422
    )


def test_needs_the_share_permission_and_a_signed_in_user(people):
    w, p = people, people.people
    assert (
        w.client.get("/api/v1/directory", headers=p.rev.h).status_code == 403
    )  # reviewer role cannot share
    assert w.client.get("/api/v1/directory", headers=p.norole.h).status_code == 403
    assert w.client.get("/api/v1/directory").status_code == 401


def test_other_organizations_are_invisible(people):
    w = people
    assert all(x["full_name"] != "Anita Desai" for x in find(w, w.admin_b))
    assert find(w, w.admin_b) == []
