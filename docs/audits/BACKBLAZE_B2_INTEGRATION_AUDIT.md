# Backblaze B2 Integration Audit

**Date:** 2026-10-30  
**Scope:** Read-only investigation of the current repository. No application code, configuration, infrastructure, or database was modified.  
**Secret handling:** Credential values, tokens, and private object URLs are omitted. Only variable names, bucket identifiers, and non-secret settings are recorded.

Legend used throughout this report:

| Label | Meaning |
|---|---|
| **Verified** | Observed directly in repository source, tracked files, or local env files (values of secrets were not recorded). |
| **Inferred** | Follows from the code path or from Backblaze/SDK behavior, and was not confirmed against a live B2 account. |
| **Missing** | No implementation or configuration was found in this repository. |
| **Recommended** | Change proposed for the new document management system (DMS). Not implemented. |

---

## 1. Executive summary

The application has a working native Backblaze B2 client beside an Azure Blob client. Uploads and downloads go through the FastAPI process. The browser and mobile clients never receive the application key. Private-object downloads use a time-limited B2 download authorization token, with a default lifetime of 60 minutes borrowed from the Azure SAS setting.

**Verified:** the integration method is the native B2 API through `b2sdk`, not the S3-compatible API. There is no `boto3` client, no configured S3 endpoint, and no configured region.

**Verified:** the active storage provider is selected by `STORAGE_PROVIDER` (`azure` or `backblaze`). The code default is `azure`. The local FastAPI env files that exist in this workspace set Azure storage and do not set any `BACKBLAZE_*` variable. `apps/fastapi/.env` is not present. Whether production Azure App Service has Backblaze enabled cannot be determined from this repository.

**Verified:** documentation and a tracked status file name the bucket `aaditech-erp-test-v2`. The settings default is a different name, `attachmentserp-b2`. The live bucket, its privacy setting, the key’s capability list, and the account region were not confirmed against Backblaze.

**Verified security issue:** `apps/fastapi/BACKBLAZE_STATUS.txt` is tracked by git and contains a plaintext application key ID and application key. Those values are intentionally absent from this report. Treat the key as exposed and rotate it.

The current design can be reused as a pattern (server-side credentials, prefix object keys, SQL metadata, short-lived download tokens). It should not be reused as the production DMS bucket, the object-key scheme, or the upload path. The new system needs its own private buckets per environment, tenant-scoped keys, direct uploads for 100 MB files, PostgreSQL version metadata, and metered retention.

---

## 2. Existing architecture

### 2.1 Placement in the stack

**Verified.** Storage is a shared service used by feature services. Routers accept multipart uploads, enforce auth and validation, and call feature services. Feature services build object keys and call the storage factory. Repositories persist the object key and file metadata in SQL Server.

```
React / API client
    -> FastAPI router (multipart UploadFile, auth)
        -> feature service (validation, object key, DB metadata)
            -> blob_storage_factory
                -> backblaze_blob_service   when STORAGE_PROVIDER=backblaze
                -> azure_blob_service       when STORAGE_PROVIDER=azure (default)
                    -> single configured bucket / container
```

| Layer | File | Role |
|---|---|---|
| Settings | `apps/fastapi/app/core/config.py` | `BACKBLAZE_*` and `STORAGE_PROVIDER` |
| B2 client | `apps/fastapi/app/services/backblaze_blob_service.py` | Authorize, upload, download, delete, download tokens |
| Provider switch | `apps/fastapi/app/services/blob_storage_factory.py` | Selects the upload provider and locates existing objects across Azure and B2 |
| Feature storage | `notice_attachment_storage.py`, `homework_attachment_storage.py`, `syllabus_attachment_storage.py`, `support_attachment_storage.py`, `enrollment_document_storage.py`, `activity_gallery_media_storage.py`, `icon_auto_uploader.py` | Prefixes, size/type checks, object keys |
| HTTP | Feature routers plus `apps/fastapi/app/routers/icons.py` | Multipart upload and, for some features, authenticated byte proxy |
| Web display | `apps/web/src/utils/mediaUrl.ts` | Allows absolute URLs whose host is `backblazeb2.com` or `blob.core.windows.net` |
| Dependency | `apps/fastapi/requirements.txt` | `b2sdk>=2.0.0` |

### 2.2 Integration method

**Verified.** Native B2 API.

```34:41:apps/fastapi/app/services/backblaze_blob_service.py
    try:
        import b2sdk.v2 as b2_mod
    except ImportError as exc:
        raise ValidationException(
            "Backblaze SDK (b2sdk) is not installed. "
            "Run: pip install 'b2sdk>=2.0.0' and restart the API."
        ) from exc
```

```73:76:apps/fastapi/app/services/backblaze_blob_service.py
    info = b2.InMemoryAccountInfo()
    api = b2.B2Api(info)
    try:
        api.authorize_account("production", key_id, app_key)
```

`production` here is the B2 account realm passed to `authorize_account`. It is not an AWS region and not an environment name. The download host is discovered after authorization via `api.account_info.get_download_url()` (`backblaze_blob_service.py` lines 237–239).

**Missing:** S3-compatible endpoint, `boto3`, AWS SDK, SigV4 presigned PUT/GET, and any region setting.

**Inferred.** A friendly download host such as `f003.backblazeb2.com` appears only as an example in `apps/fastapi/STORAGE_SETUP_PROMPT.md` (line 186). That host is not configured in code. The running account’s download URL is whatever B2 returns at authorize time.

### 2.3 Provider selection and mixed Azure/B2 reads

**Verified.** Uploads always use the active provider:

```11:27:apps/fastapi/app/services/blob_storage_factory.py
def get_active_provider_name() -> StorageProviderName:
    provider = (settings.STORAGE_PROVIDER or "azure").lower()
    if provider in ("azure", "backblaze"):
        return provider  # type: ignore[return-value]
    raise ValidationException(f"Unknown storage provider: {provider}")
```

Reads do not trust `STORAGE_PROVIDER` alone. `locate_object_provider` (`blob_storage_factory.py` lines 53–106) checks Azure URL shape, then calls `blob_exists` on B2 and Azure. If the object exists on both, the active upload provider wins. Deletes follow the same location result and refuse to guess when the provider is unknown (`blob_storage_factory.py` lines 177–203).

**Inferred.** This exists so historical Azure objects remain readable after `STORAGE_PROVIDER` is switched to `backblaze`.

### 2.4 Call sites

**Verified.** These features upload through `get_storage_service().upload_bytes`:

| Feature | Storage module | Object prefix |
|---|---|---|
| Notices | `notice_attachment_storage.py` | `notice-attachments/` |
| Homework | `homework_attachment_storage.py` | `homework-attachments/` |
| Syllabus | `syllabus_attachment_storage.py` | `syllabus-attachments/` |
| Support queries | `support_attachment_storage.py` | `support-query-attachments/` |
| Support release notes | `support_attachment_storage.py` | `support-release-notes/` |
| Enrollment documents | `enrollment_document_storage.py` | `enrollment-documents/` |
| Student photos | `enrollment_document_storage.py` | `student-photos/` |
| Activity gallery photos | `activity_gallery_media_storage.py` | `activity-gallery-media/` |
| Sidebar icons | `icon_auto_uploader.py` | `sidebar-icons/` |

The same prefixes are recognized when turning a stored path back into a B2 download URL (`backblaze_blob_service.py` lines 14–24). Azure’s prefix list is the same set except it omits `sidebar-icons/` (`azure_blob_service.py` lines 236–245).

**Verified documentation drift.** `STORAGE_SETUP_PROMPT.md` and `BACKBLAZE_STATUS.txt` describe prefixes `homework/`, `notices/`, and `activity-gallery/`. The code uses the longer prefixes above. The status file also says startup calls `auto_upload_icons_to_storage()`. `app/main.py` does not. Icons upload on the first call to `GET /icons/sidebar` (`icon_auto_uploader.py` lines 98–107, `icons.py` lines 16–37, `main.py` line 188).

Profile images uploaded from the profile endpoint are written to local disk under `static/profile-images/`, not to B2 (`profile_image_service.py` lines 224–248). Cloud student photos that already live under `student-photos/` or `enrollment-documents/` are left in cloud storage (`profile_image_service.py` lines 143–156).

### 2.5 Database

**Verified.** Persistence is SQL Server via SQLAlchemy (`config.py` lines 39–45, `DB_DRIVER` default `ODBC Driver 18 for SQL Server`). File bytes are not the system of record, except a legacy `activity_gallery_media.file_content` column that new photo uploads set to `None` (`activity_gallery_service.py` lines 529–537).

Metadata that is stored:

| Table | Model | Columns relevant to storage |
|---|---|---|
| `communication_notice_attachments` | `app/models/notice.py` lines 49–63 | `tenant_id`, `file_name`, `file_path`, `file_type`, `file_size_kb`, `uploaded_at`, `uploaded_by`, soft-delete flags |
| `homework_attachments` | `app/models/homework.py` lines 58–68 | `file_name`, `file_path`, `file_type`, `file_size_kb`, `uploaded_at`, `uploaded_by`. Tenant is on the parent homework row. |
| `syllabus` attachments | `app/models/syllabus.py` lines 50–53 | `file_name`, `file_path`, `file_type`, `file_size_kb` |
| Support | `app/models/support.py` lines 21–24 and 81–84 | file name, path, type, size in KB |
| `activity_gallery_media` | `app/models/activity_gallery.py` lines 38–55 | `file_name`, `original_file_name`, `file_path`, `file_content`, `file_size` (bytes) |
| `students` | `app/models/student.py` lines 25–26 | `birth_certificate_url`, `photo_url` |

`file_path` stores the object key (for example `notice-attachments/{name}`), a legacy relative path, or sometimes a full URL. Enrollment storage explicitly refuses to persist a time-limited URL (`enrollment_document_storage.py` lines 45–56). Notice responses replace `file_path` with a fresh download URL at read time (`notice_service.py` lines 282–291). The database value itself stays the object key.

**Missing:** bucket name, storage provider, B2 file version id, checksum, encryption mode, retention date, and a tenant storage-usage ledger.

---

## 3. Configuration inventory

| Configuration | Finding | Status |
|---|---|---|
| Storage provider | Backblaze B2 is implemented. Azure Blob is the code default and the provider configured in local env files. | **Verified** code; live provider depends on process env, which is not fully visible here |
| Integration method | Native B2 API (`b2sdk.v2`). Not the S3-compatible API. | **Verified** |
| Endpoint | Not configured. After `authorize_account("production", ...)`, the download URL comes from the account info. | **Verified** absence of an endpoint setting. Runtime host **not verified** |
| Region | No region field. B2 chooses the account cluster. | **Missing** in this repo. Live region **not verified** |
| Bucket name | Settings default `attachmentserp-b2` (`config.py` lines 110–112). Docs and `BACKBLAZE_STATUS.txt` name `aaditech-erp-test-v2`. Local env files do not set `BACKBLAZE_BUCKET_NAME`. | Default and documented name **verified**. Effective runtime bucket **not verified** |
| Bucket type | Code treats the bucket as private and issues download authorization tokens. Nothing in the repo sets or reads the bucket ACL. `get_blob_url` still builds an anonymous download URL. | Privacy is **inferred** from comments and token usage, not verified in the B2 console |
| Application key ID | Variable `BACKBLAZE_KEY_ID`. Value omitted. Also present in plaintext in tracked `BACKBLAZE_STATUS.txt`. | **Verified** |
| Application key | Variable `BACKBLAZE_APP_KEY`. Value omitted. Also present in plaintext in tracked `BACKBLAZE_STATUS.txt`. | **Verified** |
| Key name | Status file refers to application key name `aaditech-erp-test-key-v2`. | **Verified** as documentation only |
| Access permissions | No capability list, bucket restriction, or prefix restriction is stored in code or env examples. | **Missing** / not verified |
| SDK / library | `b2sdk>=2.0.0` in `apps/fastapi/requirements.txt` line 19. Exact installed version is not pinned. `python-multipart` is present for form uploads. `azure-storage-blob` is the other provider. `boto3` is absent. | **Verified** |
| Configuration source | `pydantic-settings` plus `python-dotenv`. Env file path is `ENV_FILE` or `apps/fastapi/.env` (`config.py` lines 9–16, 24–29). No secret manager, Key Vault reference, or Coolify secret store appears in the repo. | **Verified** for the loading mechanism. Production secret store **not verified** |

Auth failure text hardcodes the documented bucket even when settings use another name:

```56:59:apps/fastapi/app/services/backblaze_blob_service.py
    return ValidationException(
        "Backblaze B2 rejected BACKBLAZE_KEY_ID/BACKBLAZE_APP_KEY "
        "(invalid or revoked application key). Create a new Application Key "
        "for bucket aaditech-erp-test-v2, update the env file, and restart the API."
    )
```

`BACKBLAZE_STATUS.txt` records a historical `bad_auth_token` failure against the documented key. That is a status note, not a live probe performed for this audit.

Buckets are not created by the application. `ensure_bucket_exists` only calls `get_bucket_by_name` and raises if the bucket is missing (`backblaze_blob_service.py` lines 111–127). Azure, by contrast, creates its container on upload (`azure_blob_service.py` lines 48–56).

---

## 4. Environment variables

### 4.1 Required names and purpose

| Name | Purpose |
|---|---|
| `ENV_FILE` | Optional override of the dotenv path. Default file is `apps/fastapi/.env` relative to the FastAPI app root (`config.py` lines 9–15). |
| `ENVIRONMENT` | `development`, `test`, `staging`, or `production` (`config.py` lines 37 and 144–151). Does not by itself select a B2 bucket. |
| `STORAGE_PROVIDER` | `azure` or `backblaze`. Default `azure` (`config.py` lines 114–117). Controls new uploads. |
| `BACKBLAZE_KEY_ID` | B2 application key ID. Empty default. Never log or return the value. |
| `BACKBLAZE_APP_KEY` | B2 application key secret. Empty default. |
| `BACKBLAZE_BUCKET_NAME` | Single bucket for all B2 objects. Default `attachmentserp-b2` when unset (`config.py` lines 110–112). |
| `AZURE_BLOB_SAS_EXPIRY_MINUTES` | Lifetime used for Azure SAS and, when the caller does not pass an expiry, for B2 download tokens. Default 60 (`config.py` lines 96–99, `backblaze_blob_service.py` lines 259–262). |
| `AZURE_STORAGE_CONNECTION_STRING` | Azure credential. Still consulted for legacy objects when B2 is the upload provider. |
| `AZURE_CONTAINER_NAME` | Azure container. Code default `attachmentserp`. |

There is no `BACKBLAZE_ENDPOINT`, `BACKBLAZE_REGION`, `BACKBLAZE_BUCKET_PUBLIC`, or second bucket variable.

### 4.2 What is actually set in this workspace

| File | Git | Backblaze variables | Other storage notes |
|---|---|---|---|
| `apps/fastapi/.env` | Ignored by `apps/fastapi/.gitignore` line 18. File is absent. | None | Not a configuration source today |
| `apps/fastapi/.env.dev` | Ignored by `.env.*` (`apps/fastapi/.gitignore` line 19) | **Absent** | `AZURE_STORAGE_CONNECTION_STRING` is set. `AZURE_CONTAINER_NAME=attachmentserp`. `STORAGE_PROVIDER` is unset, so the code default `azure` applies. |
| `apps/fastapi/.env.test` | Ignored by `.env.*` | **Absent** | Same Azure container name `attachmentserp`. Connection string is set. No `STORAGE_PROVIDER`. |
| `apps/fastapi/.env.example` | Tracked | **Absent** | Documents database placeholders only. Does not document B2. |
| `apps/web/.env`, `.env.development`, `.env.test`, `.env.capacitor`, `.env.example` | Web `.env` exists locally | No `BACKBLAZE_*` names | Frontend build does not receive B2 credentials. |
| `apps/web/config/contabo.env` and `contabo.env.example` | Example is the template | No B2 names | Web/deploy host settings, not object storage. |

**Verified.** Starting the API from this workspace, with only the env files above, uses Azure for new uploads. Backblaze runs only when `STORAGE_PROVIDER=backblaze` and the three `BACKBLAZE_*` variables are injected by the process environment or by an env file that is not in this workspace.

### 4.3 CI and production

**Verified.** `.github/workflows/development_preschoolproductapi.yml` installs `apps/fastapi/requirements.txt` (which includes `b2sdk`) and deploys the FastAPI tree to Azure Web App `PreschoolProductAPI`, slot `Production`. The workflow does not define `STORAGE_PROVIDER` or `BACKBLAZE_*`. Those would have to exist as App Service application settings outside the repo.

**Missing in repo:** per-environment B2 credentials, a secret manager reference, and a staging slot workflow for storage.

---

## 5. Upload/download implementation

### 5.1 How files are uploaded

**Verified.** Backend proxy. The client posts `multipart/form-data` to FastAPI. The router reads the entire body into memory (`await file.read()` or `file.file.read()`), the feature service validates it, then `bucket.upload_bytes` sends the bytes to B2.

```148:159:apps/fastapi/app/services/backblaze_blob_service.py
        api = _b2_api()
        bucket = api.get_bucket_by_name(_bucket_name())

        bucket.upload_bytes(
            data_bytes=content,
            file_name=blob_name.strip(),
            content_type=content_type or "application/octet-stream",
        )

        logger.info("Uploaded to B2: %s", blob_name)
        return blob_name.strip()
```

The returned value is the object key, not a URL.

**Missing:** direct-to-B2 upload, `get_upload_url`, upload authorization tokens, and S3 presigned PUT.

### 5.2 How files are downloaded

Two patterns exist.

**Pattern A — time-limited B2 URL returned in JSON. Verified** for notices, homework, syllabus, support, and enrollment.

`generate_authorized_download_url` (`backblaze_blob_service.py` lines 245–278):

1. Expiry defaults to `AZURE_BLOB_SAS_EXPIRY_MINUTES` (60), converted to seconds.
2. Values below 60 seconds are raised to 60.
3. `bucket.get_download_authorization(file_name_prefix=<full object key>, valid_duration_in_seconds=seconds)` returns a download token.
4. The URL is `{downloadUrl}/file/{bucket}/{objectKey}?Authorization={token}`.

Notice list/detail responses put that URL in `file_path` so a browser can open it without an `Authorization` header (`notice_service.py` lines 282–291). Homework does the same in `add_attachment` (`homework_service.py` lines 457–461).

**Pattern B — authenticated API proxy. Verified** for activity-gallery media when the object is on B2, and as a secondary path for notice bytes.

Gallery responses replace the B2 path with `/api/activity-galleries/{gallery_id}/media/{media_id}/content` (`activity_gallery_service.py` lines 113–117). `GET .../content` and `GET .../download` require `get_current_user` and a viewer context, then `download_bytes` streams the object through the API (`activity_gallery_router.py` lines 346–397).

Notices also expose `GET /communications/notices/{notice_id}/attachments/{attachment_id}/content`, which checks view permission and calls `download_notice_attachment_bytes` (`notice.py` lines 275–306). The primary URL in the notice payload is still the B2 token URL, not this proxy.

`download_bytes` (`backblaze_blob_service.py` lines 209–227) uses `bucket.download_file_by_name`, writes to a `BytesIO`, and returns the full buffer. The API holds the whole object in memory.

### 5.3 How private files are accessed

**Verified.** The storage layer assumes a private bucket and attaches a download authorization token. Application authorization happens before that token is minted: the feature service only resolves URLs for rows the current user is allowed to load. The token URL is then a bearer capability until it expires. B2 does not re-check the ERP permission.

Gallery B2 photos keep the permission check on every byte request because the client must call the authenticated proxy.

**Inferred.** If the bucket were actually public, `get_blob_url` and any leaked object key would be anonymously readable. This audit did not call the B2 API, so the ACL is unconfirmed.

### 5.4 Presigned URL expiry

| Item | Value | Status |
|---|---|---|
| Mechanism | Native `get_download_authorization`, not S3 presign | **Verified** |
| Default lifetime | 60 minutes via `AZURE_BLOB_SAS_EXPIRY_MINUTES` | **Verified** |
| Minimum | 60 seconds | **Verified** |
| Dedicated B2 expiry setting | None | **Missing** |
| Upload presign | None | **Missing** |
| Scope of the token | `file_name_prefix` is the full object key | **Verified** call. **Inferred** B2 behavior: the token authorizes every file name that starts with that prefix, not a single exact key |

### 5.5 Deletion

**Verified.** `delete_blob` loads the latest file version with `get_file_info_by_name` and calls `api.delete_file_version(file_version.id_, file_version.file_name)` (`backblaze_blob_service.py` lines 192–206). Missing files return without error. Any exception is logged and swallowed.

Feature services delete only after an authorization check, for example notice manage permission (`notice.py` lines 309–318) and gallery manage access (`activity_gallery_service.py` `delete_media`). `delete_mixed_blob` will not delete an Azure object with the B2 client (`blob_storage_factory.py` lines 177–203).

**Missing:** delete-all-versions, hide-file / soft delete in B2, lifecycle rules, legal hold, and a retention window. A failed B2 delete still leaves the database row removed in flows that commit first (notice attachment delete commits, then deletes the object: `notice_service.py` lines 727–736).

**Inferred.** If the bucket has B2 file versioning enabled, deleting the latest version can leave older versions. The application never lists versions.

### 5.6 Multipart uploads

**Missing** in application code. Callers buffer the full file, then call `upload_bytes`. There is no large-file start, part upload, or complete call.

**Inferred.** `b2sdk`’s `upload_bytes` can switch to the large-file API above the SDK part threshold (commonly 100 MB). Current feature limits are 3–50 MB, so that path is not exercised by this application. This was not confirmed by reading the installed `b2sdk` sources.

### 5.7 Size and type validation

**Verified.** Validation is per feature, not inside `backblaze_blob_service`. The B2 client accepts any bytes and any content type.

| Feature | Max size | Type check | Source |
|---|---|---|---|
| Notices | 3 MB | PDF, JPEG, PNG | `notice_attachment_storage.py` lines 23–29, 99–106 |
| Homework | 10 MB | `.jpg`, `.jpeg`, `.png`, `.webp`, `.pdf`, `.doc`, `.docx`, `.txt` | `homework_attachment_storage.py` lines 17–19, 31–40 |
| Syllabus | 10 MB | pdf, Office, jpg/jpeg/png | `syllabus_attachment_storage.py` lines 17–31, 43–52 |
| Support query | 10 MB | pdf, doc, docx, png, jpg, jpeg | `support_attachment_storage.py` lines 21–24, 42–49 |
| Release notes | 10 MB | pdf, doc, docx | `support_attachment_storage.py` lines 22–25, 81–86 |
| Enrollment | 10 MB | images; birth certificate also PDF | `enrollment_document_storage.py` lines 25–29, 71–83 |
| Gallery photo | 4 MB original image; gallery total 10 MB; max 20 items | jpg, jpeg, png, jfif | `activity_gallery_media_storage.py` lines 25–27, 72–74; `activity_gallery_access.py` lines 21–23 |
| Gallery video files | 50 MB constant exists | mp4, mov, avi | `activity_gallery_media_storage.py` lines 26–27, 75–80. Video galleries currently reject file upload and accept YouTube links (`activity_gallery_service.py` lines 511–513) |
| Sidebar icons | None | Hardcoded PNG | `icon_auto_uploader.py` lines 84–88 |

Images pass through `prepare_file_for_storage`, which recompresses them to JPEG, targets about 400 KB, and caps stored images at 500 KB (`image_compression_service.py` lines 15–17 and 30–50). Original content type is not what B2 stores for those images.

Extension checks use the client filename. Notice uploads also check the client `Content-Type`. There is no magic-byte sniffer except Pillow failing closed on images it cannot decode.

**Missing:** a global 100 MB policy, an API gateway body limit in this repo, and server-side MIME sniffing for non-images.

### 5.8 Checksums

**Missing** in application code. No SHA-256 or SHA-1 is calculated or stored on the attachment rows.

**Inferred.** The native B2 `b2_upload_file` API requires a SHA-1, and `b2sdk` computes it inside `upload_bytes`. That digest is not returned to the database.

### 5.9 Errors and retries

**Verified.**

| Operation | Behavior | Location |
|---|---|---|
| Auth failure | Cache is cleared. API returns HTTP-level `ValidationException`. Log line records exception type and whether key id, app key, and bucket are non-empty. Values are not logged. | `backblaze_blob_service.py` lines 45–84 |
| Upload failure | Logged with object key, raised as `"File upload failed"` | lines 161–165 |
| Download missing | `"File not found"` | lines 223–224 |
| Download other errors | `"File download failed"` | lines 225–227 |
| Delete failure | Logged and ignored | lines 205–206 |
| Exists check failure | Logged, returns `False` | lines 183–189 |
| URL generation failure | `resolve_download_url` logs and returns the original stored path | lines 340–346 |
| Application retry | None | — |
| Idempotency | Icons skip upload when `blob_exists` is true. User uploads always create a new key. | `icon_auto_uploader.py` lines 78–82 |

**Inferred.** `b2sdk` has its own HTTP retries. This repository does not configure them. An exists-check failure can make `locate_object_provider` miss a B2 object and then refuse to delete it.

### 5.10 Object keys and folders

**Verified.** B2 has no directories. The app uses key prefixes. The usual key is:

```text
{prefix}/{tenant_id}_{entity_id}_{UTC timestamp YYYYMMDDHHMMSS}_{8 hex chars of uuid4}{extension}
```

Examples:

- Notices: `notice-attachments/{tenant_id}_{notice_id}_{suffix}{ext}` (`notice_attachment_storage.py` lines 118–120)
- Homework: `homework-attachments/{tenant_id}_{homework_id}_{suffix}{ext}` (`homework_attachment_storage.py` lines 52–54)
- Syllabus: `syllabus-attachments/{tenant_id}_{syllabus_id}_{suffix}{ext}` (`syllabus_attachment_storage.py` lines 64–66)
- Support queries: `support-query-attachments/{tenant_id}_{query_id}_{suffix}{ext}` (`support_attachment_storage.py` lines 61–63)
- Enrollment: `{enrollment-documents|student-photos}/{tenant_id}_{user_id}_{document_type}_{suffix}{ext}` (`enrollment_document_storage.py` lines 95–98)
- Gallery: `activity-gallery-media/{tenant_id}_{gallery_id}_{suffix}.jpg` (`activity_gallery_media_storage.py` lines 99–134)
- Release notes: `support-release-notes/note_{note_id}_{suffix}{ext}` — no tenant id (`support_attachment_storage.py` lines 92–94)
- Icons: `sidebar-icons/{fixed name}.png` (`icon_auto_uploader.py` line 76)

Tenant id is embedded in the file name. It is not a top-level prefix such as `tenants/{id}/...`. All tenants share one bucket and one prefix per feature.

### 5.11 Multiple buckets

**Missing.** One `BACKBLAZE_BUCKET_NAME` for the whole process. No tenant bucket, no environment bucket switch, no bucket argument on `upload_bytes`.

### 5.12 Metadata stored with the object

**Verified.** Only `content_type` is sent (`upload_bytes` `content_type` argument). No B2 `file_info` custom metadata, no cache-control, no content-disposition, no legal hold.

Business metadata lives in SQL Server, as listed in section 2.5.

---

## 6. Security assessment

### 6.1 Control review

| Question | Assessment | Evidence |
|---|---|---|
| Are buckets private? | **Inferred, not verified.** Code mints download tokens and comments call the bucket private. ACL is not set in code and was not read from B2. | `backblaze_blob_service.py` lines 245–253, 317–322 |
| Are credentials restricted to the required bucket? | **Not verified.** No capability or bucket-id restriction is in the repo. The status file names a key but does not list its capabilities. | `config.py` lines 102–113 |
| Are credentials separated by environment? | **Missing.** One trio of variables. `ENVIRONMENT` does not select a key or bucket. Local dev/test env files do not define B2 at all. Production App Service settings are outside the repo. | `config.py` lines 37, 101–117 |
| Are download tokens short-lived? | **Partially.** Default 60 minutes. Floor is 60 seconds. 60 minutes is long for a bearer URL that bypasses later permission checks. | `backblaze_blob_service.py` lines 259–264; `config.py` lines 96–99 |
| Is access authorized before URL generation? | **Yes for feature APIs** that load the parent record under the current user. **No inside the storage client.** `GET /icons/sidebar` has no auth dependency and can return a download URL. | `notice.py` lines 275–280; `icons.py` lines 16–37 |
| Are credentials exposed to frontend code? | **No in source.** Web and mobile trees contain no `BACKBLAZE_KEY_ID` or `BACKBLAZE_APP_KEY`. The web app only allowlists the `backblazeb2.com` host. Download tokens are returned to the client by design. | `apps/web/src/utils/mediaUrl.ts` lines 3–16 |
| Are object keys predictable? | **Partly.** They include tenant id, entity id, a per-second timestamp, and 32 bits of randomness (`uuid4().hex[:8]`). Icon keys are fixed names. Release-note keys omit tenant id. Keys are not a substitute for a private bucket. | See section 5.10 |
| Is access logging implemented? | **Application logs only.** Upload and delete success use `logger.info`. Failures use `logger.exception`. There is no access-audit table and no B2 bucket logging configuration in the repo. | `backblaze_blob_service.py` lines 47–55, 158, 164, 204 |
| Are uploaded files scanned? | **Missing.** No malware scan, CDR, or quarantine bucket. | — |
| Encrypted in transit? | **Inferred.** `b2sdk` talks to the B2 HTTPS API. The app does not set a custom TLS policy. | `authorize_account` call |
| Encrypted at rest? | **Not configured by the app.** No customer-managed key or SSE mode is sent. Backblaze default server-side encryption was not verified for this account. | `upload_bytes` call passes only bytes, name, and content type |
| Are deletions protected? | **At the API, yes. At the storage client, no.** Feature routes require a logged-in user and a manage/edit check. `delete_blob` itself deletes whatever key it is given and swallows errors. There is no retention hold. | `notice.py` lines 309–318; `backblaze_blob_service.py` lines 192–206 |
| Legacy local files | **Public.** Matching static directories are mounted with `StaticFiles` and no auth. | `main.py` lines 196–218 |
| Secrets in git | **Yes.** Tracked `apps/fastapi/BACKBLAZE_STATUS.txt` lines 68–72 contain a key ID and application key in plaintext. | `git ls-files` includes this path |

### 6.2 Weaknesses

1. **Committed application key (critical).** `apps/fastapi/BACKBLAZE_STATUS.txt` is in git. Rotate that key in the Backblaze console, remove the file from the tree, and purge it from history. Do not reuse the documented key for the DMS. The status note already recorded `bad_auth_token`, so the key may be invalid, but exposure still requires rotation.

2. **Bearer download URLs.** A 60-minute `Authorization` query token can be forwarded, cached by intermediaries, or written into client logs. Later revocation of the user’s ERP permission does not revoke the token. Gallery’s authenticated proxy avoids this. Notices deliberately chose the token URL so browsers can open files without a header (`notice_service.py` lines 286–290).

3. **Prefix-scoped tokens.** Native `get_download_authorization` is prefix-based. Using the full key is the tightest option the API offers, and a second object whose name starts with that key would be included.

4. **Shared bucket and shared key.** Every tenant, feature, and (if one env file is copied) every environment would share one key. Compromise of the API host exposes every object the key can read. Tenant isolation is only in application checks before the token is issued.

5. **Anonymous static mounts** for any file that still exists on local disk under the same prefix names (`main.py` lines 196–218). Cloud objects are not served from these mounts, but a failed URL rewrite returns the original relative path (`backblaze_blob_service.py` lines 340–346), which the browser can request from the API host.

6. **Unauthenticated icon endpoint** can trigger uploads with the server key and return URLs (`icons.py` lines 16–37).

7. **Silent delete failures** and commit-then-delete ordering can orphan objects or leave the database pointing at a deleted object (`notice_service.py` lines 727–736).

8. **No malware scanning, no checksum, no retention.**

9. **Auth error text names a specific bucket** (`aaditech-erp-test-v2`), which leaks an internal resource name to API clients (`backblaze_blob_service.py` lines 56–59).

10. **`InMemoryAccountInfo` auth cache** (`backblaze_blob_service.py` lines 63–85) keeps the authorized session in process memory. That is normal for `b2sdk` and means the secret remains in the API process after startup.

### 6.3 Recommended improvements

These are recommendations only. This audit did not change the current ERP.

- Rotate the exposed key. Store new keys in a secret manager or host secret store, one key per environment, restricted to one bucket, with read/write limited to the prefixes that environment uses.
- Confirm in the B2 console that the bucket is private. Remove anonymous download fallbacks (`get_blob_url`) for private objects.
- Shorten download-token TTL to a few minutes. Prefer the authenticated proxy when the client can send the app JWT (web `fetch`, React Native).
- Put tenant and environment in the key prefix. Authorize in the service before minting a token, and bind the token to the exact object.
- Delete all versions or hide the file, and alert when B2 delete fails. Do the object delete before committing the metadata removal, or use an outbox.
- Add checksum, size, and provider columns. Scan uploads before they become readable.
- Remove `BACKBLAZE_STATUS.txt` from the repository and from git history after rotation.
- Require auth on `/icons/sidebar`, or stop storing UI icons in the private document bucket.

---

## 7. Deployment configuration

| Artifact | Finding |
|---|---|
| `apps/web/Dockerfile` | **Verified.** Node 22 build and nginx runtime for the React app. Build args are `VITE_*` only (lines 19–27). No B2 credentials. |
| FastAPI Dockerfile | **Missing.** `DEPLOYMENT.md` lines 331–344 show an example `python:3.11-slim` image. It is documentation, not a file in the tree. |
| Docker Compose | **Missing** as a project file. `DEPLOYMENT.md` lines 346–361 shows an example that passes `ENVIRONMENT=production` and `env_file: ./apps/fastapi/.env`. That example would load B2 variables only if that file contained them. |
| Coolify | **Missing.** No Coolify application, service, or env definition was found. |
| GitHub Actions | **Verified.** `development_preschoolproductapi.yml` builds and deploys FastAPI to Azure Web App `PreschoolProductAPI` / Production. It does not set storage env vars. `development_preschool-web-app.yml` and `azure-static-web-apps-icy-water-048cd6710.yml` deploy the frontend and do not reference B2. |
| Production configuration in repo | **Missing.** App Service application settings are not exported here. |
| Development configuration | **Verified** as Azure-only in `apps/fastapi/.env.dev` and `.env.test`. Both are gitignored. Neither enables Backblaze. |
| Dependency install | **Verified.** CI runs `pip install -r requirements.txt`, so `b2sdk` is installed on deploy even when the provider is Azure. The import is lazy, so Azure-only processes do not fail if import were skipped; CI does install it. |

`b2sdk` account info is in-memory only (`InMemoryAccountInfo`). There is no on-disk B2 credential cache in the application.

---

## 8. Existing limitations

| Limitation | Classification |
|---|---|
| Single bucket, single key, no region/endpoint settings | **Verified** |
| Default provider is Azure; this workspace does not enable B2 | **Verified** |
| Documented bucket name and code default disagree (`aaditech-erp-test-v2` vs `attachmentserp-b2`) | **Verified** |
| Docs describe prefixes and a startup icon upload that the code does not use | **Verified** |
| Uploads are fully buffered in the API process | **Verified** |
| Largest allowed user file is 10 MB (50 MB constant for gallery video files, which are not uploaded to B2 today). Notices are 3 MB. | **Verified** |
| No multipart upload API in the app | **Verified** |
| No direct-to-B2 upload | **Verified** |
| No checksum, virus scan, or object version id in the database | **Verified** |
| No document version history. A new upload creates a new key; replace flows delete the previous object. | **Verified** |
| No tenant storage quota. Gallery has a 10 MB total per gallery, which is not tenant metering. | **Verified** |
| Download token TTL is coupled to the Azure SAS setting | **Verified** |
| Delete errors are ignored | **Verified** |
| SQL Server metadata, not PostgreSQL | **Verified** |
| Exact `b2sdk` version, live bucket ACL, key capabilities, account region, and production env values | **Not verified** |
| `b2sdk` internal retry and large-file threshold | **Inferred**, not confirmed from the installed package |

---

## 9. Recommended DMS architecture

The DMS requirements (multi-tenant SaaS, private documents, 100 MB uploads, versioning, secure download, permission checks, archival, controlled deletion, usage metering, retention, React and React Native, FastAPI) do not fit the current ERP bucket or upload path. Reuse the security shape. Build a separate storage module and schema.

### 9.1 Bucket strategy

**Recommended:** create a dedicated private DMS bucket. Do not reuse `aaditech-erp-test-v2` or the ERP default `attachmentserp-b2`.

Reasons grounded in this repo:

- The documented bucket name is a test bucket and is shared with ERP attachments, student photos, and UI icons.
- One key currently has no represented prefix boundary between tenants or features.
- ERP deletes and icon uploads would share fate with DMS documents.
- The exposed key in `BACKBLAZE_STATUS.txt` must not be the DMS key.

**Recommended:** separate buckets (and separate application keys) for development, staging, and production. The current code has a single `BACKBLAZE_BUCKET_NAME` and does not switch on `ENVIRONMENT`. Copying one `.env` between environments would mix objects.

Keep buckets private. Do not enable public `file/` downloads.

### 9.2 Integration method

**Recommended:** keep the native B2 API with `b2sdk` if the team wants to stay on the existing client, and add the upload-authorization / large-file calls the current wrapper does not have.

The S3-compatible API with `boto3` is a reasonable alternative for presigned PUT and multipart, which this codebase does not implement. Choosing it would be new work, not a reuse of `backblaze_blob_service.py`. Either way, credentials stay on the server.

### 9.3 Object keys

Use prefixes as the tenant boundary:

```text
tenants/{tenant_id}/documents/{document_id}/versions/{version_number}/{object_id}/{sanitized_file_name}
```

- `tenant_id` is the first prefix so a bucket-restricted or prefix-restricted key can be audited, and so download tokens cannot be widened to another tenant by mistake.
- `object_id` is a UUID, not an 8-hex fragment and not a timestamp.
- The original file name is display metadata in PostgreSQL. It is not the only uniqueness component.
- No environment name inside a production bucket. Environment isolation is the bucket itself.
- Do not store the download URL. Store bucket, object key, and B2 file version id.

### 9.4 Direct uploads

**Recommended:** direct-to-B2 uploads for the 100 MB limit.

The current proxy reads the whole file into the API worker (`notice.py` line 260, `homework_router.py` line 357, `upload_bytes` of the full `bytes`). At 100 MB that raises memory use and request time, and it still is not multipart.

Flow:

1. Client calls FastAPI: file name, content type, size, document id.
2. API checks permission, tenant quota, 100 MB cap, and an allowlist of types.
3. API reserves a PostgreSQL version row in `pending` and returns a short-lived B2 upload URL (or large-file part URLs) plus the object key.
4. Browser or React Native uploads straight to B2.
5. Client calls FastAPI to complete. API verifies the object (size, and SHA-1 that B2 returns), stores the checksum and B2 file id, and marks the version `available`.
6. Until step 5 succeeds, the object is not linked as the current version and can be deleted by a sweeper.

Keep a small proxied upload only for files that must be transformed (the ERP JPEG recompression). DMS originals should be stored as uploaded.

### 9.5 PostgreSQL metadata

The ERP pattern of `file_name`, `file_path`, `file_type`, and `file_size_kb` is the right idea and is too thin for the DMS. Suggested tables:

- `documents`: `id`, `tenant_id`, `title`, `current_version_id`, `status` (`active`, `archived`, `deleted`), `created_by`, timestamps.
- `document_versions`: `id`, `document_id`, `tenant_id`, `version_number`, `bucket`, `object_key`, `b2_file_id`, `original_file_name`, `content_type`, `size_bytes`, `checksum_sha1`, `uploaded_by`, `created_at`, `retention_until`, `deleted_at`.
- `document_permissions` or a link to the existing permission model: who may read or delete.
- `tenant_storage_usage`: `tenant_id`, `bytes_used`, `bytes_reserved`, `updated_at`.

Never persist the `Authorization` query string. Mint it when a permitted download is requested.

The current database is SQL Server. These tables are new PostgreSQL tables for the DMS, not a migration of `communication_notice_attachments`.

### 9.6 Preventing unauthorized object access

- Private bucket. No public prefix.
- Application key restricted to the one DMS bucket. Prefer a prefix limit if the key can be scoped.
- FastAPI checks tenant and permission, then mints a download token with a short TTL (about 5 minutes) or streams bytes through an authenticated route.
- React and React Native already send the app JWT. Use that for the complete-upload and download-authorize calls. `mediaUrl.ts` can keep treating `backblazeb2.com` as a trusted host for those short-lived URLs.
- Bind tokens to the full object key. Do not pass a tenant-wide prefix.
- On permission revoke, stop issuing tokens. Accept that already issued tokens live until TTL, which is why TTL must be short. For higher sensitivity, use the authenticated proxy and do not return a B2 URL.

### 9.7 Storage usage tracking

Do not list the bucket to compute a bill. The ERP only stores `file_size_kb` on each row and never aggregates it, except the gallery’s per-gallery 10 MB cap (`activity_gallery_access.py` lines 21–23).

For the DMS:

- On complete-upload, add `size_bytes` to `tenant_storage_usage` inside the same transaction that marks the version available.
- On controlled delete after retention, subtract only when the object is actually removed from B2.
- Archived versions still count until retention expiry.
- Enforce the quota before issuing the upload URL, using `bytes_used + bytes_reserved`.
- Reconcile occasionally with B2 `list_file_versions` per tenant prefix. The ledger is the source of truth for product quotas.

### 9.8 Versioning, archive, and deletion

- A new upload inserts a new `document_versions` row and a new object key. It does not overwrite the previous key. The current ERP overwrite/delete-on-replace behavior is the wrong model for retention.
- B2 bucket versioning can be enabled as a backstop. The application should still store `b2_file_id` and should not rely on “latest name” the way `delete_file_version` of the latest info does today.
- Archive sets document status and blocks new downloads according to policy. It does not need to move objects if the prefix and metadata stay.
- Controlled deletion is a two-phase action: mark `deleted_at` / `retention_until`, hide from clients, then a job calls B2 delete for every stored file id after the retention date. Alert if B2 delete fails. Do not swallow the error as `delete_blob` does.

---

## 10. Reusable components

| Component | Reuse for DMS | Notes |
|---|---|---|
| `backblaze_blob_service.py` account setup (`InMemoryAccountInfo`, `authorize_account`, lazy import) | Reuse the pattern | Extract a new DMS client. Do not point it at the ERP bucket or the committed key. |
| `upload_bytes` | Reuse only for small server-generated files | Insufficient for 100 MB direct upload. |
| `generate_authorized_download_url` | Reuse the idea with a shorter TTL and an explicit expiry argument | Stop reading `AZURE_BLOB_SAS_EXPIRY_MINUTES` for DMS. |
| `blob_storage_factory.py` mixed Azure/B2 locator | Do not reuse for new DMS objects | It exists to read legacy ERP files. DMS should be B2-only and should record the provider on the row. |
| Feature prefix helpers and `uuid` key suffix | Reuse the prefix idea, replace the key format | Tenant must be a prefix. Use a full UUID. |
| SQL columns `file_name`, `file_path`, `file_type`, `file_size_kb` | Reuse as a conceptual model | Expand in PostgreSQL as in section 9.5. `file_path` must remain the key, never the signed URL. `enrollment_document_storage.persistable_document_path` is the pattern to copy. |
| Router auth before download | Reuse | Notice content route and gallery content route are the better pattern. JSON token URLs need a shorter life. |
| `mediaUrl.ts` host allowlist | Reuse in the React client | Add the same host check in React Native. Still require the app to obtain the URL from an authorized API. |
| Image compression | Do not apply to DMS originals by default | ERP recompression changes bytes and content type (`image_compression_service.py`). |
| `icon_auto_uploader.py` | Do not reuse | Unrelated to documents, and the endpoint is unauthenticated. |
| `b2sdk>=2.0.0` | Reuse the dependency, pin a tested version | Exact version is currently unpinned. |
| Azure client | Out of scope for the DMS | Keep it for the ERP. |

---

## 11. Required changes for DMS

New work, not a copy of the ERP service:

1. New private buckets and application keys for development, staging, and production. Confirm each bucket is private. Restrict each key to its bucket.
2. New settings: bucket, key id, key secret, download-token TTL, max upload bytes (104857600), and optional endpoint only if the S3 API is chosen. Load them from the environment or a secret manager. Do not add them to `BACKBLAZE_STATUS.txt` or to git.
3. A DMS storage module with: create upload authorization (including large-file parts above the small-file threshold), complete/verify, download authorization, and delete-by-file-id. Retries with backoff. Delete failures must surface.
4. PostgreSQL document, version, permission, and usage tables. Store B2 file id, size, and checksum.
5. FastAPI routes: reserve upload, complete upload, download (authorize or stream), archive, restore, and delete. Permission check on every one of those, scoped by `tenant_id`.
6. Clients: React and React Native upload to the B2 URL, then call complete. They send the existing JWT only to FastAPI.
7. Metering transaction and a reconciliation job.
8. Retention job that deletes B2 versions only after `retention_until`.
9. Malware scanning before a version becomes `available`, if the product requires it. The ERP has nowhere to hook this.
10. Remove or redact the tracked credential file in the ERP repo as an immediate operational fix, independent of the DMS build.

The current ERP does not need a behavior change for the DMS to exist, as long as the DMS uses a different bucket and key.

---

## 12. Open questions and risks

| Item | Why it is open | Risk if assumed |
|---|---|---|
| Is production `STORAGE_PROVIDER` actually `backblaze`? | Not present in CI or local env files. App Service settings were not read. | Building the DMS “the way production works” may copy a path that production is not using. Default code path is Azure. |
| Which bucket is live, `attachmentserp-b2` or `aaditech-erp-test-v2`? | Default and docs disagree. No local env sets the variable. | Reusing “the existing bucket” may target an empty default name or a test bucket that also holds ERP files. |
| Is that bucket private? | Not queried. | A public bucket makes object keys world-readable. The token logic would be security theater. |
| What capabilities does `aaditech-erp-test-key-v2` have? | Not in the repo. The key material is in git and was already reported as `bad_auth_token`. | The key may be invalid, overly broad, or both. |
| Which B2 region/cluster is the account in? | No setting. Example host `f003` is documentation only. | Data-residency claims cannot be made from this repo. |
| Is B2 file versioning or lifecycle enabled on the bucket? | Not in code. | Deletes of the latest version may leave recoverable copies, or may not. |
| Are production secrets only in Azure App Service? | **Inferred** from the deploy workflow. Not verified. | A second copy may exist in Coolify or on a VM. No Coolify config was found to confirm or deny that. |
| Does any deployed host still have the key from `BACKBLAZE_STATUS.txt`? | File is historical. | Rotation must include every host, not only git. |
| Should the DMS use native B2 or S3 presign? | Product choice. Native client exists; presigned multipart does not. | Picking S3 means a new client. Picking native means new upload-authorization code on top of `b2sdk`. |
| Is 60-minute token exposure acceptable for DMS documents? | Current ERP behavior. | Too long for permission-aware documents. |
| SQL Server vs PostgreSQL | ERP is SQL Server. DMS requirement is PostgreSQL. | Do not point the DMS at `communication_notice_attachments`. |

---

## Appendix A. File index

| Path | Relevance |
|---|---|
| `apps/fastapi/app/services/backblaze_blob_service.py` | B2 client |
| `apps/fastapi/app/services/blob_storage_factory.py` | Provider switch and mixed read/delete |
| `apps/fastapi/app/services/azure_blob_service.py` | Alternate provider; SAS expiry shared with B2 |
| `apps/fastapi/app/core/config.py` | Settings |
| `apps/fastapi/requirements.txt` | `b2sdk>=2.0.0` |
| `apps/fastapi/app/services/*_attachment_storage.py` and `activity_gallery_media_storage.py` | Feature upload policies and keys |
| `apps/fastapi/app/services/icon_auto_uploader.py` | Icon upload |
| `apps/fastapi/app/routers/icons.py` | Unauthenticated icon URL route |
| `apps/fastapi/app/routers/notice.py` | Notice upload and authenticated content proxy |
| `apps/fastapi/app/routers/activity_gallery_router.py` | Gallery proxy download |
| `apps/fastapi/app/main.py` | Router include and public static mounts |
| `apps/fastapi/app/models/notice.py`, `homework.py`, `syllabus.py`, `support.py`, `activity_gallery.py`, `student.py` | SQL metadata |
| `apps/web/src/utils/mediaUrl.ts` | Frontend host allowlist |
| `apps/fastapi/STORAGE_SETUP_PROMPT.md` | Stale operator notes, including example bucket and download host |
| `apps/fastapi/BACKBLAZE_STATUS.txt` | Stale status note containing live-format secrets. Do not copy. |
| `apps/fastapi/.env.example` | No B2 variables |
| `apps/fastapi/.gitignore` | Ignores `.env` and `.env.*`. Does not ignore the status file. |
| `.github/workflows/development_preschoolproductapi.yml` | API deploy, no storage env |
| `apps/web/Dockerfile` | Frontend image, no B2 |
| `DEPLOYMENT.md` | Example Docker/compose only |

## Appendix B. What this audit did not do

- No Backblaze API call, so bucket existence, privacy, region, usage, and key capabilities are unverified.
- No read of Azure App Service application settings.
- No printing or copying of key material from `BACKBLAZE_STATUS.txt` or from local env files.
- No application, infrastructure, or database change.
