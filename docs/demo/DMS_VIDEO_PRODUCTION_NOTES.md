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
