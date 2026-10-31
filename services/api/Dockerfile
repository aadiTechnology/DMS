# DMS API image (Linux). Built by Coolify from the repository; see docs/deployment/COOLIFY_DEPLOYMENT.md
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    UPLOAD_TMP_DIR=/data/uploads-tmp \
    STORAGE_LOCAL_DIR=/data/storage

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini docker-entrypoint.sh ./
COPY app ./app
COPY migrations ./migrations

RUN useradd --system --uid 10001 --no-create-home dms \
    && mkdir -p /data/uploads-tmp /data/storage \
    && chown -R dms /data \
    && chmod +x docker-entrypoint.sh
USER dms

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["./docker-entrypoint.sh"]
