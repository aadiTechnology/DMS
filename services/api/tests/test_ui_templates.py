# ruff: noqa: F811
import copy
import json
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.tenant_session import platform_session, tenant_session
from app.services.org import Conflict, Invalid
from app.ui import service
from app.ui.seed import seed_directory
from tests.test_rbac import auth, env  # noqa: F401  (fixtures)

TEMPLATES = Path(__file__).resolve().parents[3] / "design-showcase" / "templates"


def sample(key="modern-enterprise"):
    return json.loads((TEMPLATES / f"{key}.json").read_text("utf-8"))


@pytest.fixture
def catalogue(env):
    report = seed_directory(TEMPLATES, engine=env.engine)
    assert len(report["imported"]) == 5 and not report["failed"]
    env.hA = auth(env, "emp-a@x.test")
    env.adminA = auth(env, "admin-a@x.test")
    env.adminB = auth(env, "admin-b@x.test")
    return env


def available(env, h):
    r = env.client.get("/api/v1/ui-templates/available", headers=h)
    assert r.status_code == 200, r.text
    return {t["key"]: t for t in r.json()}


def choose(env, h, template_id):
    return env.client.put("/api/v1/me/ui-preferences", json={"template_id": template_id}, headers=h)


# ---- catalogue --------------------------------------------------------------------------


def test_seed_publishes_five_templates_and_is_repeatable(env):
    first = seed_directory(TEMPLATES, engine=env.engine)
    assert len(first["imported"]) == 5
    again = seed_directory(TEMPLATES, engine=env.engine)
    assert len(again["skipped"]) == 5 and not again["imported"]


def test_users_see_the_published_templates_with_their_details(catalogue):
    env = catalogue
    cards = available(env, env.hA)
    assert set(cards) == {
        "modern-enterprise",
        "premium-dark",
        "minimalist-productivity",
        "modern-saas",
        "enterprise-productivity",
    }
    card = cards["premium-dark"]
    assert (
        card["name"] == "Premium Dark"
        and card["version"] == "1.0.0"
        and card["scope"] == "platform"
    )
    assert not card["is_selected"] and "config" not in card


def test_drafts_and_archived_templates_are_invisible_to_organizations(catalogue):
    env = catalogue
    extra = sample()
    extra["key"], extra["name"] = "draft-only", "Draft Only"
    with platform_session(env.engine) as db:
        draft = service.import_platform_template(db, extra, publish=False)
        archived = service.import_platform_template(
            db, {**copy.deepcopy(extra), "key": "old-one", "name": "Old One"}, publish=True
        )
        service.archive_template(db, archived)
        draft_id, archived_id = str(draft.id), str(archived.id)
    keys = available(env, env.hA)
    assert "draft-only" not in keys and "old-one" not in keys and len(keys) == 5
    assert (
        env.client.get(f"/api/v1/ui-templates/available/{draft_id}", headers=env.hA).status_code
        == 404
    )
    assert choose(env, env.hA, draft_id).status_code == 404
    assert choose(env, env.hA, archived_id).status_code == 404


def test_full_configuration_can_be_read_for_preview(catalogue):
    env = catalogue
    t = available(env, env.hA)["modern-saas"]
    r = env.client.get(f"/api/v1/ui-templates/available/{t['id']}", headers=env.hA)
    assert r.status_code == 200 and r.json()["config"]["layout"]["sidebarVariant"] == "floating"


def test_authentication_is_required(catalogue):
    env = catalogue
    for method, path in (
        ("get", "/api/v1/ui-templates/available"),
        ("get", "/api/v1/me/ui-preferences"),
        ("put", "/api/v1/me/ui-preferences"),
    ):
        assert getattr(env.client, method)(path).status_code == 401


# ---- per-user preference ----------------------------------------------------------------


def test_each_user_has_their_own_design_within_one_tenant(catalogue):
    env = catalogue
    cards = available(env, env.hA)
    assert choose(env, env.hA, cards["premium-dark"]["id"]).status_code == 200
    assert choose(env, env.adminA, cards["modern-saas"]["id"]).status_code == 200
    mine = env.client.get("/api/v1/me/ui-preferences", headers=env.hA).json()
    theirs = env.client.get("/api/v1/me/ui-preferences", headers=env.adminA).json()
    assert (
        mine["effective"]["source"] == "user"
        and mine["effective"]["template"]["key"] == "premium-dark"
    )
    assert theirs["effective"]["template"]["key"] == "modern-saas"
    assert (
        available(env, env.hA)["premium-dark"]["is_selected"]
        and not available(env, env.hA)["modern-saas"]["is_selected"]
    )


def test_preference_persists_across_sessions(catalogue):
    env = catalogue
    pid = available(env, env.hA)["minimalist-productivity"]["id"]
    choose(env, env.hA, pid)
    new_session = auth(env, "emp-a@x.test")  # a fresh sign-in, as on another device
    got = env.client.get("/api/v1/me/ui-preferences", headers=new_session).json()
    assert (
        got["selected_template_id"] == pid
        and got["effective"]["template"]["key"] == "minimalist-productivity"
    )
    assert got["effective"]["template"]["config"]["layout"]["sidebarVariant"] == "top"


def test_one_row_per_user_even_after_many_changes(catalogue):
    env = catalogue
    cards = available(env, env.hA)
    for key in ("premium-dark", "modern-saas", "premium-dark"):
        assert choose(env, env.hA, cards[key]["id"]).status_code == 200
    with env.engine.begin() as c:
        assert c.execute(text("SELECT count(*) FROM user_ui_preferences")).scalar() == 1


def test_reset_returns_to_the_default(catalogue):
    env = catalogue
    choose(env, env.hA, available(env, env.hA)["premium-dark"]["id"])
    r = choose(env, env.hA, None)
    assert r.status_code == 200 and r.json()["selected_template_id"] is None
    assert r.json()["effective"]["source"] == "product"
    assert r.json()["effective"]["template"]["key"] == "modern-enterprise"


def test_unknown_or_malformed_choices_are_refused(catalogue):
    env = catalogue
    assert choose(env, env.hA, "00000000-0000-0000-0000-000000000000").status_code == 404
    assert (
        env.client.put(
            "/api/v1/me/ui-preferences", json={"template_id": "nope"}, headers=env.hA
        ).status_code
        == 422
    )
    assert (
        env.client.put(
            "/api/v1/me/ui-preferences", json={"template_id": None, "x": 1}, headers=env.hA
        ).status_code
        == 422
    )


def test_choosing_a_design_does_not_touch_data_or_permissions(catalogue):
    env = catalogue
    before = env.client.get("/api/v1/me/permissions", headers=env.hA).json()
    choose(env, env.hA, available(env, env.hA)["premium-dark"]["id"])
    assert env.client.get("/api/v1/me/permissions", headers=env.hA).json() == before
    assert env.client.get("/api/v1/documents/mine", headers=env.hA).status_code == 200


# ---- fallback chain ---------------------------------------------------------------------


def test_fallback_order_user_then_tenant_then_product_then_system(catalogue):
    env = catalogue
    cards = available(env, env.hA)
    got = lambda h: env.client.get("/api/v1/me/ui-preferences", headers=h).json()["effective"]
    assert (
        got(env.hA)["source"] == "product" and got(env.hA)["template"]["key"] == "modern-enterprise"
    )
    assert (
        env.client.put(
            "/api/v1/ui-templates/tenant-default",
            json={"template_id": cards["modern-saas"]["id"]},
            headers=env.adminA,
        ).status_code
        == 200
    )
    assert got(env.hA)["source"] == "tenant" and got(env.hA)["template"]["key"] == "modern-saas"
    choose(env, env.hA, cards["premium-dark"]["id"])
    assert got(env.hA)["source"] == "user" and got(env.hA)["template"]["key"] == "premium-dark"
    assert got(env.adminA)["source"] == "tenant"  # others keep the organization default


def test_a_template_archived_after_being_chosen_is_skipped(catalogue):
    env = catalogue
    cards = available(env, env.hA)
    choose(env, env.hA, cards["premium-dark"]["id"])
    with platform_session(env.engine) as db:
        t = db.get(service.UiTemplate, cards["premium-dark"]["id"])
        service.archive_template(db, t)
    effective = env.client.get("/api/v1/me/ui-preferences", headers=env.hA).json()["effective"]
    assert effective["source"] == "product" and effective["template"]["key"] == "modern-enterprise"


def test_system_theme_when_nothing_is_published(env):
    env.h = auth(env, "emp-a@x.test")
    effective = env.client.get("/api/v1/me/ui-preferences", headers=env.h).json()["effective"]
    assert effective == {"source": "system", "template": None}


def test_a_stored_template_that_no_longer_validates_is_never_applied(catalogue):
    env = catalogue
    cards = available(env, env.hA)
    choose(env, env.hA, cards["premium-dark"]["id"])
    with env.engine.begin() as c:  # simulate damaged data, bypassing the application
        c.execute(
            text(
                "UPDATE ui_templates SET config_json = jsonb_set(config_json, '{theme,colors,primary}', '\"url(x)\"') WHERE template_key = 'premium-dark'"
            )
        )
    effective = env.client.get("/api/v1/me/ui-preferences", headers=env.hA).json()["effective"]
    assert effective["source"] == "product"


def test_tenant_default_needs_the_organization_permission(catalogue):
    env = catalogue
    pid = available(env, env.hA)["modern-saas"]["id"]
    assert (
        env.client.put(
            "/api/v1/ui-templates/tenant-default", json={"template_id": pid}, headers=env.hA
        ).status_code
        == 403
    )
    assert env.client.get("/api/v1/ui-templates/tenant-default", headers=env.hA).status_code == 403
    assert (
        env.client.get("/api/v1/ui-templates/tenant-default", headers=env.adminA).json()[
            "template_id"
        ]
        is None
    )


# ---- isolation --------------------------------------------------------------------------


def test_preferences_and_defaults_are_isolated_between_organizations(catalogue):
    env = catalogue
    pid = available(env, env.hA)["premium-dark"]["id"]
    choose(env, env.hA, pid)
    env.client.put(
        "/api/v1/ui-templates/tenant-default", json={"template_id": pid}, headers=env.adminA
    )
    other = env.client.get("/api/v1/me/ui-preferences", headers=env.adminB).json()
    assert other["selected_template_id"] is None and other["effective"]["source"] == "product"
    assert (
        env.client.get("/api/v1/ui-templates/tenant-default", headers=env.adminB).json()[
            "template_id"
        ]
        is None
    )
    with tenant_session(
        env.tb, env.engine
    ) as db:  # row-level security: tenant B sees none of A's rows
        assert db.execute(text("SELECT count(*) FROM user_ui_preferences")).scalar() == 0
        assert db.execute(text("SELECT count(*) FROM tenant_ui_defaults")).scalar() == 0


def test_a_tenant_template_is_visible_only_inside_its_tenant(catalogue):
    env = catalogue
    extra = sample()
    extra["key"], extra["name"] = "alpha-only", "Alpha Only"
    with platform_session(env.engine) as db:
        t = service.import_platform_template(db, extra, publish=True)
        db.execute(
            text("UPDATE ui_templates SET scope='tenant', tenant_id=:t WHERE id=:i"),
            {"t": env.ta, "i": t.id},
        )
        tid = str(t.id)
    assert "alpha-only" in available(env, env.hA)
    assert "alpha-only" not in available(env, env.adminB)
    assert choose(env, env.adminB, tid).status_code == 404
    assert (
        env.client.get(f"/api/v1/ui-templates/available/{tid}", headers=env.adminB).status_code
        == 404
    )


def test_organizations_cannot_write_the_catalogue(catalogue):
    env = catalogue
    with pytest.raises(DBAPIError), tenant_session(env.ta, env.engine) as db:
        db.execute(text("UPDATE ui_templates SET template_name = 'Hacked'"))
    with pytest.raises(DBAPIError), tenant_session(env.ta, env.engine) as db:
        db.execute(
            text(
                "INSERT INTO ui_template_versions(template_id, version, config_json) SELECT id, '9.9.9', '{}' FROM ui_templates LIMIT 1"
            )
        )
    with pytest.raises(DBAPIError):
        with platform_session(env.engine) as db:  # the platform role has no access to tenant data
            db.execute(text("SELECT count(*) FROM user_ui_preferences")).scalar()


# ---- import rules -----------------------------------------------------------------------


def test_import_rules_versions_history_and_validation(env):
    with platform_session(env.engine) as db:
        t = service.import_platform_template(db, sample(), publish=True)
        assert t.status == "published" and t.version == "1.0.0"
        with pytest.raises(Conflict):
            service.import_platform_template(db, sample())  # same version again
        newer = sample()
        newer["version"] = "1.1.0"
        newer["name"] = "Modern Enterprise 2"
        t2 = service.import_platform_template(db, newer)
        assert (
            t2.id == t.id and t2.version == "1.1.0" and t2.status == "draft"
        )  # waits for publication
        older = sample()
        older["version"] = "0.9.0"
        with pytest.raises(Conflict):
            service.import_platform_template(db, older)
        with pytest.raises(Invalid):
            service.import_platform_template(db, {"schemaVersion": "1.0"})
        with pytest.raises(Invalid):
            service.import_platform_template(db, "not json")
        service.publish_template(db, t2)
        assert (
            db.execute(
                text("SELECT count(*) FROM ui_template_versions WHERE template_id = :i"),
                {"i": t.id},
            ).scalar()
            == 2
        )
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM ui_template_versions WHERE published_at IS NOT NULL AND template_id = :i"
                ),
                {"i": t.id},
            ).scalar()
            == 2
        )
        service.archive_template(db, t2)
        with pytest.raises(Conflict):
            service.publish_template(db, t2)


def test_seed_reports_invalid_files(env, tmp_path):
    (tmp_path / "bad.json").write_text('{"schemaVersion": "1.0"}', "utf-8")
    (tmp_path / "good.json").write_text(json.dumps(sample()), "utf-8")
    report = seed_directory(tmp_path, engine=env.engine)
    assert (
        len(report["imported"]) == 1
        and len(report["failed"]) == 1
        and "bad.json" in report["failed"][0]
    )
