#!/bin/sh
# Applies database migrations, then starts the API. Set RUN_MIGRATIONS=0 to skip the first step.
set -eu

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    alembic upgrade head
fi

# One worker by default: request rate limits are kept in process memory, so more workers would
# multiply the limits. Behind the Coolify proxy, trust its forwarded headers for the client address.
exec uvicorn app.main:app \
    --host 0.0.0.0 --port "${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-1}" \
    --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}"
