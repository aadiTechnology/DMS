from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.db.models import TenantMembership
from app.db.repository import TenantRepository
from app.db.tenant_session import tenant_session


class MembershipRepository(TenantRepository[TenantMembership]):
    model = TenantMembership


@pytest.fixture
def world(migrated_engine):
    """Tenant A (2 members) and tenant B (1 member), seeded as the owner role."""
    ids = SimpleNamespace(engine=migrated_engine)
    with migrated_engine.begin() as c:
        ids.a = c.execute(text("INSERT INTO tenants(name) VALUES ('A') RETURNING id")).scalar()
        ids.b = c.execute(text("INSERT INTO tenants(name) VALUES ('B') RETURNING id")).scalar()
        users = [
            c.execute(
                text("INSERT INTO users(email) VALUES (:e) RETURNING id"), {"e": f"u{i}@x.test"}
            ).scalar()
            for i in range(3)
        ]
        ins = text("INSERT INTO tenant_memberships(tenant_id,user_id) VALUES (:t,:u) RETURNING id")
        ids.a_members = [c.execute(ins, {"t": ids.a, "u": users[i]}).scalar() for i in (0, 1)]
        ids.b_members = [c.execute(ins, {"t": ids.b, "u": users[2]}).scalar()]
        ids.user_a = users[0]
    return ids


def _count(session, table="tenant_memberships") -> int:
    return session.execute(text(f"SELECT count(*) FROM {table}")).scalar()


def test_tenant_sees_only_own_rows(world):
    with tenant_session(world.a, world.engine) as s:
        assert _count(s) == 2
        assert _count(s, "tenants") == 1
    with tenant_session(world.b, world.engine) as s:
        assert _count(s) == 1


def test_raw_query_for_other_tenant_returns_nothing(world):
    """Even a hand-written query that names the other tenant is filtered by the database."""
    with tenant_session(world.a, world.engine) as s:
        rows = s.execute(
            text("SELECT id FROM tenant_memberships WHERE tenant_id = :t"), {"t": world.b}
        ).all()
    assert rows == []


def test_no_tenant_context_matches_nothing(world):
    """Deny by default: the unprivileged role without app.tenant_id sees no rows."""
    with world.engine.begin() as c:
        c.execute(text("SET LOCAL ROLE dms_app"))
        assert c.execute(text("SELECT count(*) FROM tenant_memberships")).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM tenants")).scalar() == 0


def test_cannot_insert_into_other_tenant(world):
    with (
        pytest.raises(ProgrammingError, match="row-level security"),
        tenant_session(world.a, world.engine) as s,
    ):
        s.execute(
            text("INSERT INTO tenant_memberships(tenant_id,user_id) VALUES (:t,:u)"),
            {"t": world.b, "u": world.user_a},
        )


def test_cannot_update_or_delete_other_tenant_rows(world):
    with tenant_session(world.a, world.engine) as s:
        upd = s.execute(
            text("UPDATE tenant_memberships SET status='active' WHERE id = :i"),
            {"i": world.b_members[0]},
        )
        assert upd.rowcount == 0
    with (
        pytest.raises(DBAPIError, match="permission denied"),
        tenant_session(world.a, world.engine) as s,
    ):
        s.execute(text("DELETE FROM tenant_memberships WHERE id = :i"), {"i": world.a_members[0]})
    with world.engine.connect() as c:
        assert (
            c.execute(
                text("SELECT status FROM tenant_memberships WHERE id=:i"), {"i": world.b_members[0]}
            ).scalar()
            == "invited"
        )


def test_cannot_move_row_to_other_tenant(world):
    with (
        pytest.raises(ProgrammingError, match="row-level security"),
        tenant_session(world.a, world.engine) as s,
    ):
        s.execute(
            text("UPDATE tenant_memberships SET tenant_id = :b WHERE id = :i"),
            {"b": world.b, "i": world.a_members[0]},
        )


def test_users_table_not_exposed_to_app_role(world):
    with (
        pytest.raises(ProgrammingError, match="permission denied"),
        tenant_session(world.a, world.engine) as s,
    ):
        s.execute(text("SELECT email FROM users"))


def test_context_does_not_leak_between_transactions(world):
    with tenant_session(world.a, world.engine) as s:
        assert _count(s) == 2
    with world.engine.begin() as c:
        c.execute(text("SET LOCAL ROLE dms_app"))
        assert c.execute(text("SELECT count(*) FROM tenant_memberships")).scalar() == 0


def test_repository_scopes_get_and_list(world):
    with tenant_session(world.a, world.engine) as s:
        repo = MembershipRepository(s, world.a)
        assert len(repo.list()) == 2
        assert repo.get(world.a_members[0]) is not None
        assert repo.get(world.b_members[0]) is None  # not found, existence not revealed


def test_repository_add_ignores_client_tenant_id(world):
    with world.engine.begin() as c:
        uid = c.execute(
            text("INSERT INTO users(email) VALUES ('new@x.test') RETURNING id")
        ).scalar()
    with tenant_session(world.a, world.engine) as s:
        m = MembershipRepository(s, world.a).add(user_id=uid, tenant_id=world.b)
        assert m.tenant_id == world.a


def test_repository_page_size_is_capped(world):
    with tenant_session(world.a, world.engine) as s:
        assert len(MembershipRepository(s, world.a).list(limit=10_000)) == 2


def test_rls_forced_and_enabled(world):
    with world.engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname IN ('tenants','tenant_memberships')"
            )
        ).all()
    assert len(rows) == 2 and all(r.relrowsecurity and r.relforcerowsecurity for r in rows)
