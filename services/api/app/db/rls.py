"""Row-level security helpers (defense in depth behind application-level tenant filters).

The application connects as the migration/owner user and runs each request transaction as the
unprivileged `dms_app` role (SET LOCAL ROLE), with `app.tenant_id` set for that transaction.
A transaction without a tenant context matches no rows (deny by default).
"""

APP_ROLE = "dms_app"
TENANT_SETTING = "app.tenant_id"

_CURRENT_TENANT = f"nullif(current_setting('{TENANT_SETTING}', true), '')::uuid"


def enable_tenant_rls_sql(table: str, column: str = "tenant_id") -> list[str]:
    """SQL to force tenant isolation on `table`. Use from migrations for every tenant-owned table."""
    predicate = f"{column} = {_CURRENT_TENANT}"
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY tenant_isolation ON {table} USING ({predicate}) WITH CHECK ({predicate})",
    ]


def disable_tenant_rls_sql(table: str) -> list[str]:
    return [
        f"DROP POLICY IF EXISTS tenant_isolation ON {table}",
        f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
    ]
