# DMS walkthrough video: production notes

Video 01 of the DMS series: `videos/01-dms-web-application-walkthrough.mp4` (about 5 minutes, 1600x900, H.264 video, AAC narration). Subtitles: `.srt` and `.vtt` beside it. Narration CSV: `.csv` (same column order as ScriptToVideo `slides.csv`). MP4 files are git-ignored; the scripts, subtitles and CSV are tracked.

## What was reused

| Reused from | What |
|---|---|
| `AadiProduct/dev-environment/videos/recordings/record-05-crm-rbac.mjs` | The whole pipeline, copied into `videos/record-dms-walkthrough.mjs`: Playwright browser capture at 1600x900 (Playwright is loaded from the Control Plane frontend's `node_modules`, no new dependency), Windows voice **Microsoft Zira Desktop** through `System.Speech`, narration timed to each scene, FFmpeg mix (H.264 `veryfast` crf 20, AAC 128k), SRT and VTT output, frame extraction for checking |
| `ScriptToVideo` (`Product/ScriptToVideo`) | The `slides.csv` column order for the narration CSV. The CSV can be used with that tool later; **it was not run**, because it builds slideshows from screenshots and needs an Azure Speech key that is not configured on this machine |
| FFmpeg 8.1 at `C:\softwares\ffmpeg-8.1-full_build\bin` | Mixing and probing |

Voice note: the CRM series uses the Windows voice, not Azure Speech, so this video does too. Switching to Azure neural voices means running the CSV through ScriptToVideo once an Azure key is available.

## Demo environment

- Database `dms_demo` in the local Docker container `dms-postgres-1` (port 15432). Nothing else is touched.
- `services/api/scripts/seed_demo.py` creates the fictional organization **Demo Industries**, six accounts, the organization structure, four categories and eight documents through the real API (so every rule applies). It refuses production, refuses any database whose name lacks `demo`, and writes the generated password only to `docs/demo/DMS_DEMO_ACCESS.md` (git-ignored).
- `start_demo.bat` (repository root) starts the container, the API (port 8000) and the web app (port 5173).

## Regenerate the video

The recording uploads and approves a document, so it changes demo data. Use a fresh demo database each time:

```powershell
docker exec dms-postgres-1 psql -U dms -d postgres -c "DROP DATABASE IF EXISTS dms_demo" -c "CREATE DATABASE dms_demo"
$env:DATABASE_URL = "postgresql+psycopg://dms:dms_dev@localhost:15432/dms_demo"
$env:STORAGE_LOCAL_DIR = "$PWD\services\api\.storage\demo"
cd services\api; uv run alembic upgrade head; uv run python scripts/seed_demo.py; cd ..\..
.\start_demo.bat          # API and web app
node videos\record-dms-walkthrough.mjs
```

Scene text lives in the `scenes` array of the script; edit it and re-run (speech files are cached by text). A failure leaves `videos/verification/failure.jpg`. `node videos/check-logins.mjs` signs in as every demo account through the browser and prints PASS or FAIL.

## Checks performed (observed)

- Browser sign-in for all six demo accounts: PASS (each reaches the library and signs out).
- Recording ran end to end through 13 scenes; the MP4 decodes (`ffprobe`: h264 1600x900, aac, 298.3 s); one frame per scene was extracted into `videos/verification/` and reviewed.
- The password is typed only into a masked field and the recorder fails if it ever appears on screen.

## Limits of this video

- It shows only what the web app does today: sign-in, library, search and filters, document details, upload, approvals, shared lists, archive state, organization directory, permissions page. Sharing creation, new-version upload, user/category administration, reports, dashboards and notifications have no screens yet and are said to be "still to come".
- Preview and download are described, not clicked: they open the file in a new browser tab, which the recorder does not capture.
- Subtitles are one cue per scene (the same convention as the CRM videos), so each caption is a full paragraph.
- Narration pronounces the product name as letters ("D M S") on purpose.

## Video 02: choose your design (Sprints T0-T5)

`videos/02-dms-choose-your-design.mp4` (about 3.5 minutes, 11 scenes) with `.srt`, `.vtt` and `.csv` beside it, recorded by `videos/record-appearance.mjs`. It shows: the default design, the Appearance page, previewing a design without saving, applying it, a colleague with a different design in the same organization, the choice following a person to a new sign-in, the platform administrator's Design catalogue refusing an unsafe file, importing and publishing a sixth design (Forest Calm) with no redeployment, a person choosing it, and reset to default.

**Shared pipeline:** both recorders now use `videos/lib.mjs` (speech, timing, mixing, subtitles, narration CSV, frame extraction), so there is one copy of that logic. The first video's recorder was reduced to its scenes; it has **not** been re-run since that change.

**Regenerate:** use a fresh demo database as described above (the seed now also publishes the five designs and makes the demo administrator a platform administrator), start the demo (`start_demo.bat`), then `node videos/record-appearance.mjs`. Environment overrides: `DMS_WEB_URL`, `DEMO_ACCESS_FILE`.

**Limits:** voice and subtitle conventions are the same as video 01 (Windows voice, one caption per scene); the dashboard and reports designs are mentioned as future, not shown; I looked at 3 of the 11 verification frames, not all.

## Video 03: working with documents (Sprint W2a)

`videos/03-dms-working-with-documents.mp4` (about 4 minutes, 12 scenes) with `.srt`, `.vtt` and `.csv`, recorded by `videos/record-documents.mjs` on the shared pipeline. It shows: "Uploaded by me" and editing details, adding a version, previewing a PDF on the page, restoring an old version, sharing with a colleague and the colleague seeing it, a comment on a review, rejection with a reason and sending for review again, a legal hold refusing a deletion request, deletion with a second approver and the permanent-removal warning, and the due-soon list.

**Recorded on a separate recording database** (created, seeded and deleted again), so the demo you browse was not changed; its sign-in details for that run were never shown. Two situations were set up directly in the database to keep the video short and are stated in the narration: the paid invoice's keep-until date was moved into the past (so deletion is possible), and the contract template's date was moved to about twelve days ahead (so it appears in Due soon).

**Regenerate:** create a fresh database whose name contains `demo`, run the migrations and `scripts/seed_demo.py` (set `DEMO_ACCESS_FILE` so your real access file is not overwritten), start the API and `npx vite --port <port>` against it, then `DMS_WEB_URL=http://localhost:<port> PGDATABASE=<database> DEMO_ACCESS_FILE=<file> node videos/record-documents.mjs`.

**Limits:** I looked at 3 of the 12 verification frames. Subtitles are one caption per scene. The new-version upload shows no progress bar for large files because the demo files are tiny.

## Video 04: administering the organization (Sprint W2b)

`videos/04-dms-administration.mp4` (about 4.4 minutes, 12 scenes) with `.srt`, `.vtt` and `.csv`, recorded by `videos/record-administration.mjs` on the shared pipeline. It shows: employees and their roles, the last administrator being protected, invitations, a join request being approved, a lost-device two-step reset, the audit log and search index, creating a category with review steps and rules, publishing a new rules version, tags, and editing the organization (department, project people, employee details).

**Recorded on a separate recording database** (created, seeded and deleted again), so the demo you browse was not changed. The join request is simulated: the recorder posts a registration to `/api/v1/auth/register` from inside the page, because there is no public registration screen yet (planned for W2c). The sample people are Rahul Verma and Kavita Rao.

**Regenerate:** create a fresh database whose name contains `demo`, run the migrations and `scripts/seed_demo.py` (set `DEMO_ACCESS_FILE`), start the API and `npx vite --port <port>` against it, then `DMS_WEB_URL=http://localhost:<port> DEMO_ACCESS_FILE=<file> node videos/record-administration.mjs`.

**Limits:** I looked at 3 of the 12 verification frames. Subtitles are one caption per scene. The category dialog's number fields show truncated placeholders at this width ("Review every (da...").
