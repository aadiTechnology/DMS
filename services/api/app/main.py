from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api import (
    approvals,
    audit,
    auth,
    dev_storage,
    dashboard,
    directory,
    documents,
    lifecycle,
    mfa,
    onboarding,
    org,
    platform_ui,
    rbac,
    search,
    shares,
    sso,
    taxonomy,
    ui_templates,
    versions,
)
from app.core.config import get_settings
from app.storage import dev_storage_enabled

app = FastAPI(title="DMS API", version="0.0.0", openapi_url="/api/v1/openapi.json")
app.include_router(auth.router)
app.include_router(sso.router)
app.include_router(mfa.router)
app.include_router(org.router)
app.include_router(onboarding.router)
app.include_router(rbac.router)
app.include_router(audit.router)
app.include_router(taxonomy.router)
app.include_router(documents.router)
app.include_router(versions.router)
app.include_router(approvals.router)
app.include_router(shares.router)
app.include_router(lifecycle.router)
app.include_router(directory.router)
app.include_router(ui_templates.router)
app.include_router(platform_ui.router)
app.include_router(search.router)
app.include_router(dashboard.router)
if dev_storage_enabled(get_settings()):
    app.include_router(dev_storage.router)


@app.exception_handler(IntegrityError)
def _integrity_conflict(_: Request, __: IntegrityError) -> JSONResponse:
    """Concurrent duplicate or constraint race: report a conflict, never leak SQL details."""
    return JSONResponse(status_code=409, content={"detail": "Conflict with existing data"})


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
