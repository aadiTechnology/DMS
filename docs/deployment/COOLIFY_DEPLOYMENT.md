# Deploying the DMS API on Coolify (Linux server)

Status: files prepared and checked locally with Docker Desktop (image builds, starts as a non-root user, applies all migrations to a new database, answers the health check, refuses weak production settings). **Not yet deployed to a real Coolify server**; the steps below have not been run there. Nothing here deploys anything by itself.

The repository has no web application yet (planned for Sprints 22-25), so this deploys the API only.

## What was added

| File | Purpose |
|---|---|
| `services/api/Dockerfile` | Python 3.12 image, dependencies from the lock file, runs as user `dms` (not root), health check on `/api/v1/health` |
| `services/api/docker-entrypoint.sh` | Runs `alembic upgrade head`, then starts uvicorn behind the proxy (`--proxy-headers`) |
| `services/api/.dockerignore` | Keeps tests, caches and local files out of the image |
| `docker-compose.coolify.yml` | API + PostgreSQL 16 + ClamAV, all settings from environment variables; required ones fail the deploy if missing |
| `.env.coolify.example` | Variable names to set in Coolify (no values) |
| `.gitattributes` | Forces Unix line endings for shell scripts and Dockerfiles (a Windows checkout would otherwise break the container) |
| `services/api/app/jobs.py` | Command for scheduled maintenance (`python -m app.jobs expire-uploads|index-content|all`) |

`docker-compose.yml` (developer database only, fixed throwaway password) is unchanged and must not be used on a server.

## Before the first deploy (you)

1. **Backblaze production bucket and key**, separate from the test bucket and from the ERP: private bucket, key restricted to that bucket with `listBuckets, listFiles, readFiles, writeFiles, deleteFiles, shareFiles`. Enter the values only in Coolify.
2. **SMTP account** for outgoing mail (production refuses the console mailer).
3. **A domain** for the API, for example `dms-api.example.com`, pointing at the server.
4. Generate secrets on your machine, not in chat: `SECRET_KEY` (32+ random characters), `POSTGRES_PASSWORD`, and optionally `MFA_ENCRYPTION_KEY` (a Fernet key).
5. Make sure the server has about 2 GB of free memory: ClamAV alone uses roughly 1 GB while its signatures load.

## Deploy

1. Coolify: **New Resource** -> the Git repository -> build pack **Docker Compose** -> branch of your choice -> compose file `docker-compose.coolify.yml`.
2. **Environment Variables:** add every name from `.env.coolify.example`. Required (the deploy stops if missing): `POSTGRES_PASSWORD`, `SECRET_KEY`, `APP_BASE_URL`, `API_BASE_URL`. In production the application itself also refuses to start without `STORAGE_PROVIDER=backblaze` with the three `DMS_B2_*` values, `SCANNER_BACKEND=clamav`, `EMAIL_BACKEND=smtp` and a real `SECRET_KEY`.
3. **Domain:** give the `api` service your domain with port **8000**. Coolify's proxy provides HTTPS.
4. Deploy. Migrations run on every start. Check the deployment logs for `Application startup complete`, then open `https://<your domain>/api/v1/health` (expects `{"status":"ok"}`).
5. **Scheduled tasks** (Coolify -> the `api` service -> Scheduled Tasks), command run inside the `api` container:
   - every 5 minutes: `python -m app.jobs index-content`
   - every 15 minutes: `python -m app.jobs expire-uploads`
6. **Backups:** schedule backups of the `postgres` service in Coolify (volume `dms_pgdata`). The documents themselves live in Backblaze, so also keep file versioning on in the bucket. Test a restore before real use.

## Notes

- **Staging first:** to try the stack before SMTP/ClamAV/B2 exist, set `ENVIRONMENT=staging`, `STORAGE_PROVIDER=local`, `SCANNER_BACKEND=dev`, `EMAIL_BACKEND=console`. Local files are then kept in the container and lost on redeploy; never put real documents there. The development scanner does not scan.
- **Single worker:** `WEB_CONCURRENCY=1` because rate limits are held in process memory. Scale by running more containers only after the limits move to a shared store (hardening sprint).
- **Client addresses:** the API trusts the proxy's forwarded headers (`FORWARDED_ALLOW_IPS=*`) so login and search limits count real clients. Keep the API reachable only through Coolify's proxy (do not publish port 8000 on the host).
- **Upload size:** 100 MB by default (`DMS_MAX_UPLOAD_BYTES`). Uploads are streamed to the `dms_uploads_tmp` volume first; keep a few hundred MB free.
- **Database access:** the application connects as the database owner and then switches to restricted roles per request (that is what enforces tenant isolation). Use the bundled PostgreSQL service, or an external server on which that user may create roles (migrations create `dms_app` and `dms_auth`).
- **Rollback:** migrations only move forward in production. Roll back application code only to a version whose migrations are already applied, or restore a backup.
- **Secrets:** nothing in the repository holds a real value. If a key is ever exposed, rotate it in Backblaze/SMTP and update Coolify.

## Verified here / not verified

Verified locally: image build, non-root start, migrations to head on an empty database, health check, `python -m app.jobs all`, production settings refusal, compose file validation, new unit tests for the jobs. **Not verified:** a real Coolify deployment, HTTPS and proxy headers, the ClamAV container (image not pulled here), the SMTP path, and the Backblaze production bucket.
