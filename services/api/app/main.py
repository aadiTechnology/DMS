from fastapi import FastAPI

from app.api import audit, auth, memberships, rbac

app = FastAPI(title="DMS API", version="0.0.0", openapi_url="/api/v1/openapi.json")
app.include_router(auth.router)
app.include_router(memberships.router)
app.include_router(rbac.router)
app.include_router(audit.router)


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
