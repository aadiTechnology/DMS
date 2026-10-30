from fastapi import FastAPI

app = FastAPI(title="DMS API", version="0.0.0", openapi_url="/api/v1/openapi.json")


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
