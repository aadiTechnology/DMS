# DMS web image (Linux). Build context is the REPOSITORY ROOT (the web app uses the shared ui-engine package):
#   docker build -f apps/web/Dockerfile -t dms-web .
# Serves the built single-page app and forwards /api to the API container; see docs/deployment/COOLIFY_DEPLOYMENT.md
FROM node:22-alpine AS build
WORKDIR /repo
COPY package.json package-lock.json tsconfig.base.json ./
COPY packages/ui-engine/package.json packages/ui-engine/
COPY apps/web/package.json apps/web/
RUN npm ci --workspace @dms/web --include-workspace-root
COPY packages/ui-engine packages/ui-engine
COPY apps/web apps/web
RUN npm run build --workspace @dms/web

FROM nginxinc/nginx-unprivileged:1.27-alpine
# Largest request body the proxy accepts (uploads go through the API); keep it a little above DMS_MAX_UPLOAD_BYTES.
ENV NGINX_MAX_BODY=110m \
    API_UPSTREAM=http://api:8000
COPY apps/web/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /repo/apps/web/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
