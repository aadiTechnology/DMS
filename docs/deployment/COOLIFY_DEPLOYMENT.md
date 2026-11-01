# Deploying the DMS on Coolify (Linux server)

Status: the files are prepared and the **whole stack (web app, API, PostgreSQL) has been built and run locally with Docker** from the same compose file Coolify will use, including the first-administrator steps, a document upload and the checks listed at the end. It has **not been deployed to a real Coolify server** yet; the Coolify steps below have not been run there. Nothing in this repository deploys anything by itself.

## What you get

One public address (for example `https://dms.example.com`) served by three containers that Coolify starts together:

| Container | What it does | Public? |
|---|---|---|
| `web` | Serves the web application and forwards `/api` to the API | **Yes** (your domain, port 8080) |
| `api` | The DMS API; applies database updates each time it starts | No |
| `postgres` | The database (volume `dms_pgdata`) | No |
| `clamav` | Optional virus scanner, **off by default** | No |

Because the browser only ever talks to one address, no cross-site (CORS) settings are needed.

## Files

| File | Purpose |
|---|---|
| `docker-compose.coolify.yml` | The whole stack; every setting comes from environment variables, and missing required ones stop the deploy |
| `.env.coolify.example` | The variable names to fill in (no values) |
| `apps/web/Dockerfile`, `apps/web/nginx.conf.template` | Builds the web app and serves it with nginx (runs as a non-root user; forwards `/api`; allows uploads up to `NGINX_MAX_BODY`; long-lived caching only for built files; basic security headers) |
| `services/api/Dockerfile`, `docker-entrypoint.sh` | The API image (runs as user `dms`, migrates, then starts) |
| `services/api/app/provision.py` | Command that creates the **first organization and administrator** and prints a one-time sign-in link |
| `services/api/app/jobs.py` | Scheduled maintenance commands |
| `services/api/app/ui/templates/` | The five standard designs shipped inside the API image and published at start (a test keeps them identical to `design-showcase/templates/`) |
| `.gitattributes` | Keeps Unix line endings in scripts and Dockerfiles |

`docker-compose.yml` (a developer database with a throwaway password) must never be used on a server.

## Two ways to start: pick one

| | A. Trial first (recommended while email is not ready) | B. Production |
|---|---|---|
| `ENVIRONMENT` | `staging` | `production` |
| Email | `EMAIL_BACKEND=console` (emails are not sent; use the link command below) | `smtp` with your provider's values |
| Storage | Backblaze **test** bucket (or `local`, kept on a volume but never for real documents) | Backblaze production bucket (required) |
| Virus scan | `none` | `none` (allowed on purpose) or `clamav` |

Production refuses to start if it would be unsafe: a weak `SECRET_KEY`, local storage, any mailer except smtp, or no scanner without the explicit `ALLOW_UNSCANNED_UPLOADS=true`. Staging is looser so you can try everything. **Moving from A to B is only changing variables and redeploying.**

## Before you start (you)

1. **A server** with Coolify and about 2 GB free memory (add about 1 GB if you turn on the virus scanner).
2. **A domain** with a DNS `A` record pointing at the server. Until you have one, Coolify can give a temporary address to try the stack.
3. **Document storage:** a private Backblaze bucket and an application key limited to it (`listBuckets, listFiles, readFiles, writeFiles, deleteFiles, shareFiles`). Never reuse the ERP bucket.
4. **Secrets generated on your own computer, not in chat:** `SECRET_KEY` (32+ random characters) and `POSTGRES_PASSWORD`; optionally `MFA_ENCRYPTION_KEY` (a Fernet key).
5. **Email** (later, see below).

## Deploy

1. Coolify -> **New Resource** -> your Git repository -> build pack **Docker Compose** -> compose file `docker-compose.coolify.yml`.
2. **Environment Variables:** add the names from `.env.coolify.example`. Required: `POSTGRES_PASSWORD`, `SECRET_KEY`, `APP_BASE_URL`, `API_BASE_URL` (both set to your public address, for example `https://dms.example.com`, no trailing slash).
3. **Domain:** give the **`web`** service your domain with port **8080**. Do **not** give the `api` service a domain. Coolify provides HTTPS.
4. Deploy. When it finishes, open `https://<your domain>/api/v1/health` (expects `{"status":"ok"}`) and then `https://<your domain>/`.
5. **Create your organization and first administrator** (Coolify -> the `api` service -> **Terminal**):

   ```bash
   python -m app.provision create-org --name "Your Company" --admin-email you@yourcompany.com --admin-name "Your Name" --slug your-company
   ```

   It prints a one-time link (valid 48 hours, not written to any log). Open it, choose a password, then sign in. There is no screen for creating an organization on purpose.
6. **Invite everyone else** from the People page. Until email works, the invitation email is not delivered. Use this to get a one-time link for any existing person and send it yourself:

   ```bash
   python -m app.provision link person@yourcompany.com
   ```

7. **The five standard designs** are published automatically each time the API starts (safe to repeat; set `SEED_DESIGNS=0` to turn this off), so people can choose one on the Appearance page. Optional, to manage designs yourself: make your account a platform administrator (this role has no screen; production also needs two-step verification on that account), then use the **Design catalogue** page:

   ```bash
   python -m app.platform_admin grant you@yourcompany.com
   ```

8. **Scheduled tasks** (Coolify -> `api` -> Scheduled Tasks), run inside the `api` container:
   - every 5 minutes: `python -m app.jobs index-content`
   - every 15 minutes: `python -m app.jobs expire-uploads`
9. **Backups:** schedule backups of the `postgres` service (volume `dms_pgdata`). Documents live in Backblaze; keep bucket versioning on. Test a restore before real use.

## Email (Brevo, Zoho ZeptoMail or any provider)

Set these four values and `EMAIL_BACKEND=smtp`, then redeploy: `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT` (usually 587), `EMAIL_SMTP_USER`, `EMAIL_SMTP_PASSWORD`, and `EMAIL_FROM` (an address on your verified domain). **Switching provider later is only changing these values.** Brevo and similar providers send only after your sending domain's DNS records are verified, which can take up to 48 hours; until then use the `link` command above.

## Turning virus scanning on later

Set `SCANNER_BACKEND=clamav`, `ALLOW_UNSCANNED_UPLOADS=false` and `COMPOSE_PROFILES=scan`, then redeploy. This starts the `clamav` container (needs about 1 GB of memory; the first start downloads its signatures). If your Coolify version ignores compose profiles, remove the line `profiles: ["scan"]` from the `clamav` service in `docker-compose.coolify.yml` instead. Files uploaded before scanning was turned on stay as they were; their record says "not scanned".

## Google and Microsoft sign-in (later)

Register the application with each provider (their redirect address is `<your domain>/sso-callback`), then set `SSO_GOOGLE_CLIENT_ID` and/or `SSO_MICROSOFT_CLIENT_ID`. The buttons appear by themselves. People must already have an account (invited); a provider never creates one.

## Notes

- **Passwords with special characters:** `POSTGRES_PASSWORD` is passed to the API as its own value (the API builds the database address from separate parts and escapes it), so it may contain any character, including `@ : / % # ?` and spaces. Do not put the password inside a `DATABASE_URL` yourself; if you ever set `DATABASE_URL` by hand, special characters in it must be percent-encoded.
- **Single worker:** `WEB_CONCURRENCY=1` because request rate limits are held in memory. Do not run several API containers yet.
- **Upload size:** 100 MB by default (`DMS_MAX_UPLOAD_BYTES`). `NGINX_MAX_BODY` (default 110 MB) must stay a little above it.
- **Database access:** the API connects as the database owner and switches to restricted roles per request (that enforces tenant isolation). Use the bundled PostgreSQL or an external server where that user may create roles.
- **Updating:** push to the branch Coolify watches (or press Redeploy). Database updates run on start. Migrations only move forward; roll back code only to a version whose migrations are already applied, or restore a backup.
- **Secrets:** nothing in the repository holds a real value. If a key is ever exposed, rotate it at the provider and update Coolify.
- **Staging with local storage** keeps files on the `dms_storage` volume; treat them as disposable.

## Verified here / not verified

**Verified locally (same compose file, Docker Desktop):** both images build; the stack also starts and migrates with a database password containing `@ : / % # ?` and a space; the stack starts with the database healthy first; the web address serves the application, deep links, security headers and the API through one address; the API is not reachable except through the web address; the first-administrator command creates an organization and a one-time link that works once; sign-in, a reload, creating a category, uploading a document through the proxy and opening it (`videos/check-deployment.mjs`, all checks passed); the API restarted and came back healthy with the designs published once (a second start skipped them); production refuses to start without a scanner decision (also unit tests); the `scan` profile adds the ClamAV container (configuration only).

**Not verified:** a real Coolify server (HTTPS, domain, Coolify's handling of compose profiles and magic variables, terminal and scheduled tasks), the ClamAV container actually running (image not pulled), real email delivery, the Backblaze production bucket, a restore from backup, and behaviour under load. A content security policy is not set yet (planned for hardening).
