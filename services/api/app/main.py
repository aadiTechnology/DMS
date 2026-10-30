from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api import audit, auth, onboarding, org, rbac

app = FastAPI(title="DMS API", version="0.0.0", openapi_url="/api/v1/openapi.json")
app.include_router(auth.router)
app.include_router(org.router)
app.include_router(onboarding.router)
app.include_router(rbac.router)
app.include_router(audit.router)


@app.exception_handler(IntegrityError)
def _integrity_conflict(_: Request, __: IntegrityError) -> JSONResponse:
    """Concurrent duplicate or constraint race: report a conflict, never leak SQL details."""
    return JSONResponse(status_code=409, content={"detail": "Conflict with existing data"})


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
