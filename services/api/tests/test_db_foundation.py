import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from tests.conftest import alembic_config

TABLES = {
    "tenants",
    "users",
    "tenant_memberships",
    "user_sessions",
    "roles",
    "role_permissions",
    "user_role_assignments",
    "audit_events",
    "departments",
    "branches",
    "projects",
    "designations",
    "employee_profiles",
    "project_memberships",
    "auth_tokens",
    "registration_requests",
    "identity_links",
    "mfa_recovery_codes",
    "categories",
    "category_versions",
    "metadata_field_definitions",
    "tags",
    "documents",
    "document_associations",
    "document_tags",
    "document_versions",
    "document_access_grants",
    "document_search",
    "approval_requests",
    "approval_assignments",
    "approval_events",
}


def _tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def test_upgrade_then_downgrade_roundtrip(empty_db_url):
    cfg = alembic_config(empty_db_url)
    engine = create_engine(empty_db_url)
    command.upgrade(cfg, "head")
    assert _tables(engine) == TABLES
    command.downgrade(cfg, "base")
    assert _tables(engine) == set()
    command.upgrade(cfg, "head")
    assert _tables(engine) == TABLES
    engine.dispose()


def test_models_match_migration(migrated_engine):
    """Autogenerate finds no drift between ORM models and the migration."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db import models  # noqa: F401
    from app.db.base import Base

    with migrated_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def _tenant(conn) -> str:
    return str(
        conn.execute(text("INSERT INTO tenants(name) VALUES ('Acme') RETURNING id")).scalar()
    )


def _user(conn, email: str) -> str:
    q = text("INSERT INTO users(email) VALUES (:e) RETURNING id")
    return str(conn.execute(q, {"e": email}).scalar())


def test_defaults_and_utc_timestamps(migrated_engine):
    with migrated_engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO tenants(name) VALUES ('Acme') RETURNING status, timezone, "
                "default_language, data_region, created_at"
            )
        ).one()
    assert (row.status, row.timezone, row.default_language, row.data_region) == (
        "active",
        "Asia/Kolkata",
        "en",
        "india",
    )
    assert row.created_at.tzinfo is not None


def test_email_unique_case_insensitive(migrated_engine):
    with migrated_engine.begin() as conn:
        _user(conn, "a@example.com")
    with pytest.raises(IntegrityError), migrated_engine.begin() as conn:
        _user(conn, "A@Example.com")


def test_membership_unique_per_tenant_user(migrated_engine):
    with migrated_engine.begin() as conn:
        t, u = _tenant(conn), _user(conn, "e@example.com")
        ins = text("INSERT INTO tenant_memberships(tenant_id,user_id) VALUES (:t,:u)")
        conn.execute(ins, {"t": t, "u": u})
    with pytest.raises(IntegrityError), migrated_engine.begin() as conn:
        conn.execute(ins, {"t": t, "u": u})


def test_user_can_belong_to_multiple_tenants(migrated_engine):
    with migrated_engine.begin() as conn:
        u = _user(conn, "multi@example.com")
        for _ in range(2):
            t = _tenant(conn)
            conn.execute(
                text("INSERT INTO tenant_memberships(tenant_id,user_id) VALUES (:t,:u)"),
                {"t": t, "u": u},
            )
        n = conn.execute(text("SELECT count(*) FROM tenant_memberships")).scalar()
    assert n == 2


def test_membership_requires_existing_tenant_and_user(migrated_engine):
    with pytest.raises(IntegrityError), migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tenant_memberships(tenant_id,user_id) VALUES "
                "(gen_random_uuid(), gen_random_uuid())"
            )
        )


def test_referenced_tenant_cannot_be_hard_deleted(migrated_engine):
    """ORG-008: referenced entities are deactivated, not deleted."""
    with migrated_engine.begin() as conn:
        t, u = _tenant(conn), _user(conn, "x@example.com")
        conn.execute(
            text("INSERT INTO tenant_memberships(tenant_id,user_id) VALUES (:t,:u)"),
            {"t": t, "u": u},
        )
    with pytest.raises(IntegrityError), migrated_engine.begin() as conn:
        conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": t})


def test_invalid_status_rejected(migrated_engine):
    with pytest.raises(IntegrityError), migrated_engine.begin() as conn:
        conn.execute(text("INSERT INTO tenants(name,status) VALUES ('X','bogus')"))
