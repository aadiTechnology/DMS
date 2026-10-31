/**
 * DMS web application walkthrough (Sprint W1).
 * Reuses the CRM series pipeline from AadiProduct/dev-environment/videos/recordings/record-05-crm-rbac.mjs:
 * Playwright viewport capture at 1600x900, Microsoft Zira Desktop narration, FFmpeg H.264/AAC, SRT and VTT.
 * Also writes a narration CSV that uses the ScriptToVideo slides.csv column order.
 *
 * Needs the demo API (8000) and web app (5173) running against the demo database, and the
 * git-ignored docs/demo/DMS_DEMO_ACCESS.md. The password is read only to type it into masked fields.
 * Uploading and approving change demo data: re-seed a fresh demo database before recording again.
 */
import { spawn } from 'node:child_process'
import crypto from 'node:crypto'
import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import { performance } from 'node:perf_hooks'
import { fileURLToPath } from 'node:url'

const require = createRequire(
  'C:/Users/lenovo/AadiTech/Product/AadiProduct/MultiTenant/Aadi-MultiTenant-Platform/frontend/package.json',
)
const { chromium } = require('playwright')

const here = path.dirname(fileURLToPath(import.meta.url))
const repo = path.resolve(here, '..')
const outDir = here
const workDir = path.join(outDir, '.work')
const frameDir = path.join(outDir, 'verification')
const speechScript = path.join(workDir, 'speak.ps1')
const origin = 'http://localhost:5173'
const NAME = '01-dms-web-application-walkthrough'
const upload = path.join(outDir, 'assets', 'Service Agreement - Globex Logistics.pdf')

const password = loadPassword()
const who = {
  employee: 'sameer.patil@demo.dms.test',
  reviewer: 'meera.joshi@demo.dms.test',
  admin: 'asha.kulkarni@demo.dms.test',
  manager: 'rohan.deshmukh@demo.dms.test',
  project: 'priya.nair@demo.dms.test',
}

function loadPassword() {
  const text = fs.readFileSync(path.join(repo, 'docs/demo/DMS_DEMO_ACCESS.md'), 'utf8')
  const match = text.match(/Temporary password for every account below: `([^`]+)`/)
  if (!match) throw new Error('The demo password was not found in docs/demo/DMS_DEMO_ACCESS.md')
  return match[1]
}

function redact(error) {
  const message = error instanceof Error ? (error.stack ?? error.message) : String(error)
  return message.split(password).join('[redacted]')
}

function run(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { windowsHide: true })
    let stderr = ''
    child.stderr.on('data', (chunk) => (stderr += chunk.toString()))
    child.on('error', reject)
    child.on('close', (code) =>
      code === 0 ? resolve(stderr) : reject(new Error(`${command} exited ${code}: ${stderr.slice(0, 800)}`)),
    )
  })
}

function ensureSpeechScript() {
  fs.mkdirSync(workDir, { recursive: true })
  fs.writeFileSync(
    speechScript,
    `
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$text = [System.IO.File]::ReadAllText($env:SPEAK_TEXT, [System.Text.Encoding]::UTF8)
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = 0
$synth.SelectVoice('Microsoft Zira Desktop')
$synth.SetOutputToWaveFile($env:SPEAK_WAV)
$synth.Speak($text)
$synth.Dispose()
`.trim(),
    'utf8',
  )
}

async function synthesize(narration) {
  const id = crypto.createHash('sha256').update(narration).digest('hex').slice(0, 16)
  const wav = path.join(workDir, `${id}.wav`)
  if (!fs.existsSync(wav) || fs.statSync(wav).size < 1000) {
    const textFile = path.join(workDir, `${id}.txt`)
    fs.writeFileSync(textFile, narration, 'utf8')
    await new Promise((resolve, reject) => {
      const child = spawn('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', speechScript], {
        windowsHide: true,
        env: { ...process.env, SPEAK_TEXT: textFile, SPEAK_WAV: wav },
      })
      let stderr = ''
      child.stderr.on('data', (chunk) => (stderr += chunk.toString()))
      child.on('error', reject)
      child.on('close', (code) => (code === 0 ? resolve() : reject(new Error(`Speech failed (${code}): ${stderr.slice(0, 400)}`))))
    })
  }
  return wav
}

async function probeDuration(file) {
  const child = spawn('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', file], { windowsHide: true })
  let stdout = ''
  child.stdout.on('data', (chunk) => (stdout += chunk.toString()))
  const code = await new Promise((resolve) => child.on('close', resolve))
  const seconds = Number(stdout.trim())
  if (code !== 0 || !Number.isFinite(seconds) || seconds <= 0) throw new Error(`ffprobe failed for ${path.basename(file)}`)
  return seconds
}

async function click(locator) {
  await locator.waitFor({ state: 'visible' })
  await locator.scrollIntoViewIfNeeded()
  const box = await locator.boundingBox()
  if (box) {
    await locator.page().mouse.move(box.x + Math.min(28, box.width / 2), box.y + Math.min(18, box.height / 2))
    await locator.page().waitForTimeout(250)
  }
  await locator.click()
}

async function signIn(page, email) {
  await page.goto(origin + '/', { waitUntil: 'domcontentloaded' })
  await page.getByLabel('Email').fill(email)
  const field = page.getByLabel('Password')
  await field.fill(password)
  if ((await field.getAttribute('type')) !== 'password') throw new Error('The password field is not masked')
  await click(page.getByRole('button', { name: 'Sign in' }))
  await page.getByRole('heading', { name: 'Documents', exact: true }).waitFor()
}

async function signOut(page) {
  await click(page.getByRole('button', { name: 'Sign out' }))
  await page.getByRole('button', { name: 'Sign in' }).waitFor()
}

const nav = (page, name) => click(page.getByRole('link', { name }))

async function assertNoSecret(page) {
  const text = await page.locator('body').innerText()
  if (text.includes(password)) throw new Error('The demo password is visible on screen')
}

const scenes = [
  {
    chapter: 'Chapter 1 — Introduction',
    title: 'Sign-in page',
    narration:
      'This is the new D M S web application. It is a multi tenant document management system for small and medium organizations. Every person belongs to one organization, and sees only what their role and each document allow. This walkthrough uses a fictional organization called Demo Industries, with sample documents. You will sign in as an employee, a reviewer, an administrator, a department manager and a project manager.',
    actions: 'Open the sign-in page.',
    expected: 'The DMS sign-in form is visible.',
    run: async (page) => {
      await page.goto(origin + '/', { waitUntil: 'domcontentloaded' })
      await page.getByRole('button', { name: 'Sign in' }).waitFor()
    },
  },
  {
    chapter: 'Chapter 2 — Employee',
    title: 'Employee signs in and sees the document library',
    narration:
      'Sameer is an employee in the Finance department. He signs in with his work email and password. The password is typed into a masked field. After sign in, the document library opens. It lists only the documents Sameer is allowed to see, with the category, classification, status, version and size of each.',
    actions: 'Sign in as the employee.',
    expected: 'The Documents page lists documents with classification and status chips.',
    run: async (page) => {
      await signIn(page, who.employee)
      await page.getByText('Leave Policy 2026').first().waitFor()
    },
  },
  {
    chapter: 'Chapter 2 — Employee',
    title: 'Search and filters',
    narration:
      'Search looks through titles, file names, metadata and the text inside documents. Searching for acme finds the invoice and the vendor agreement. The classification filter narrows results further, and counts are calculated only over documents Sameer may see, so nothing leaks through the numbers.',
    actions: 'Search for acme, then filter by classification.',
    expected: 'Acme documents are listed; the filter keeps confidential documents only.',
    run: async (page) => {
      await page.getByLabel('Search documents').fill('acme')
      await click(page.getByRole('button', { name: 'Search', exact: true }))
      await page.getByText('Invoice INV-1001 Acme Supplies').first().waitFor()
      await page.waitForTimeout(1200)
      await click(page.getByLabel('Classification'))
      await click(page.getByRole('option', { name: /^Confidential/ }))
      await page.getByText('Invoice INV-1001 Acme Supplies').first().waitFor()
    },
  },
  {
    chapter: 'Chapter 2 — Employee',
    title: 'Document details, metadata and versions',
    narration:
      'Opening a document shows its details. The invoice carries the metadata its category requires, such as the invoice number and vendor, the date until which it must be kept, and its version history. Preview and download are separate rights. Each issues a short lived secure link, and every download is recorded in the audit log.',
    actions: 'Open the invoice detail page.',
    expected: 'Details, metadata, versions with Preview and Download buttons, and the retention date are shown.',
    run: async (page) => {
      await click(page.getByRole('link', { name: 'Invoice INV-1001 Acme Supplies' }))
      await page.getByTestId('doc-title').waitFor()
      await page.getByText('Keep until').waitFor()
      await page.getByRole('button', { name: 'Download' }).first().waitFor()
    },
  },
  {
    chapter: 'Chapter 2 — Employee',
    title: 'Upload a document that needs approval',
    narration:
      'Now Sameer uploads a contract. He chooses the Contracts category, picks the file, and the form asks for what that category requires: a department and a contract reference. The category is configured so that documents are reviewed before release, and the form says so. The file is checked for its real type and scanned before it is stored.',
    actions: 'Open Upload, choose the Contracts category, select a file, fill the required fields and upload.',
    expected: 'A success message says the document is waiting for approval.',
    run: async (page) => {
      await nav(page, 'Upload')
      await page.getByRole('heading', { name: 'Upload a document' }).waitFor()
      await click(page.getByLabel('Category'))
      await click(page.getByRole('option', { name: 'Contracts' }))
      await page.getByText('reviewed before they are released').waitFor()
      await page.getByLabel('File', { exact: true }).setInputFiles(upload)
      await page.getByLabel('Title (defaults to the file name)').fill('Service Agreement - Globex Logistics')
      await click(page.getByLabel('Department'))
      await click(page.getByRole('option', { name: 'Finance' }))
      await page.getByLabel(/Contract reference/).fill('CT-0031')
      await click(page.getByRole('button', { name: 'Upload', exact: true }))
      await page.getByText('waiting for approval').waitFor()
    },
  },
  {
    chapter: 'Chapter 3 — Reviewer',
    title: 'Reviewer approves',
    narration:
      'Meera is a reviewer. After she signs in, the menu shows how many approvals are waiting for her. She opens the new service agreement, reads the history, and approves it with a comment. A rejection would require a reason. Nobody can approve their own upload, and every decision is recorded.',
    actions: 'Sign out, sign in as the reviewer, open Approvals and approve the new agreement.',
    expected: 'The review dialog opens and the item leaves the queue after approval.',
    run: async (page) => {
      await signOut(page)
      await signIn(page, who.reviewer)
      await nav(page, 'Approvals')
      await page.getByRole('heading', { name: 'Approvals waiting for you' }).waitFor()
      const row = page.getByRole('row', { name: /Service Agreement - Globex Logistics/ })
      await click(row.getByRole('button', { name: 'Review' }))
      await page.getByLabel('Comment (required to reject)').fill('Terms match the approved template.')
      await page.waitForTimeout(1000)
      await click(page.getByRole('button', { name: 'Approve', exact: true }))
      await page.getByRole('row', { name: /Service Agreement - Globex Logistics/ }).waitFor({ state: 'detached' })
    },
  },
  {
    chapter: 'Chapter 4 — Administrator',
    title: 'Administrator sees every document',
    narration:
      'Asha is the organization administrator. Her library includes documents others cannot see, such as the highly confidential salary letters, and archived documents. Administrator access to restricted documents is an audited privilege, so every use leaves a record. Filtering by status shows the archived remote work guidelines.',
    actions: 'Sign in as the administrator and filter by Archived.',
    expected: 'The administrator sees the salary letters and the archived guidelines.',
    run: async (page) => {
      await signOut(page)
      await signIn(page, who.admin)
      await page.getByText('Salary Revision Letters FY26').first().waitFor()
      await page.waitForTimeout(1500)
      await click(page.getByLabel('Status'))
      await click(page.getByRole('option', { name: 'Archived' }))
      await page.getByText('Remote Work Guidelines 2023').first().waitFor()
    },
  },
  {
    chapter: 'Chapter 4 — Administrator',
    title: 'Document lifecycle',
    narration:
      'Documents have a lifecycle. An approved document can be archived, which keeps it readable but closed to new versions and edits, and an archived document can be restored. Categories also define how long a document must be kept and when it should be reviewed. Legal holds and approved deletion already work in the system programming interface, and will get screens in a later release.',
    actions: 'Open the archived document.',
    expected: 'The Restore from archive button is shown.',
    run: async (page) => {
      await click(page.getByRole('link', { name: 'Remote Work Guidelines 2023' }))
      await page.getByRole('button', { name: 'Restore from archive' }).waitFor()
    },
  },
  {
    chapter: 'Chapter 4 — Administrator',
    title: 'Organization structure',
    narration:
      'The organization page shows the departments, branches, projects and designations that documents are filed against, and the employee directory. Access rules use this structure. For example, confidential finance documents are visible to the Finance department and to its manager.',
    actions: 'Open Organization and browse the tabs.',
    expected: 'Departments, projects and employees are listed.',
    run: async (page) => {
      await nav(page, 'Organization')
      await page.getByText('Finance').first().waitFor()
      await page.waitForTimeout(1500)
      await click(page.getByRole('tab', { name: 'Projects' }))
      await page.getByText('Apollo ERP Rollout').waitFor()
      await page.waitForTimeout(1200)
      await click(page.getByRole('tab', { name: 'Employees' }))
      await page.getByText('Priya Nair').waitFor()
    },
  },
  {
    chapter: 'Chapter 4 — Administrator',
    title: 'Roles and permissions',
    narration:
      'The account page lists exactly what the signed in person is allowed to do. Roles grant actions, such as upload, approve or archive. Whether a person can open one particular document is decided separately, from its classification, its owner, its department and project, and any direct sharing.',
    actions: 'Open Account.',
    expected: 'The permission groups are displayed.',
    run: async (page) => {
      await nav(page, 'Account')
      await page.getByText('What your roles allow').waitFor()
    },
  },
  {
    chapter: 'Chapter 5 — Managers',
    title: 'Department manager',
    narration:
      'Rohan manages the Finance department. He sees the confidential finance documents for his department, including invoices and contracts, because the access policy gives department managers visibility into their own department. He does not see the salary letters, which belong to Human Resources.',
    actions: 'Sign in as the department manager.',
    expected: 'Finance documents are listed, the salary letters are not.',
    run: async (page) => {
      await signOut(page)
      await signIn(page, who.manager)
      await page.getByText('Invoice INV-1002 Northwind Logistics').first().waitFor()
      await page.waitForTimeout(1500)
      if ((await page.getByText('Salary Revision Letters FY26').count()) > 0) throw new Error('Manager can see HR records')
    },
  },
  {
    chapter: 'Chapter 5 — Managers',
    title: 'Project manager and sharing',
    narration:
      'Priya manages the Apollo project. An employee shared the Acme invoice with her directly, with permission to view and download. The shared page lists what has been shared with you and what you have shared with others. Sharing can expire, can be withdrawn at any time, and never gives more than the person role already allows.',
    actions: 'Sign in as the project manager and open Shared.',
    expected: 'The shared invoice is listed with view and download access.',
    run: async (page) => {
      await signOut(page)
      await signIn(page, who.project)
      await nav(page, 'Shared')
      await page.getByRole('cell', { name: 'Invoice INV-1001 Acme Supplies' }).waitFor()
      await page.getByText('View and download').waitFor()
    },
  },
  {
    chapter: 'Chapter 6 — Summary',
    title: 'What is available and what comes next',
    narration:
      'This first release of the web application covers sign in, the document library with search and filters, document details with versions and retention, upload with validation, approvals, sharing lists, lifecycle archiving, the organization directory, and role based permissions. Still to come are the screens for sharing and uploading new versions, administration of users and categories, reports and dashboards, and notifications. Thank you for watching.',
    actions: 'Return to the library.',
    expected: 'The Documents page is visible.',
    run: async (page) => {
      await nav(page, 'Documents')
      await page.getByRole('heading', { name: 'Documents', exact: true }).waitFor()
    },
  },
]

function stamp(seconds) {
  const whole = Math.max(0, seconds)
  const pad = (value, size = 2) => String(value).padStart(size, '0')
  return `${pad(Math.floor(whole / 3600))}:${pad(Math.floor((whole % 3600) / 60))}:${pad(Math.floor(whole % 60))},${pad(Math.round((whole - Math.floor(whole)) * 1000), 3)}`
}

function writeSubtitles(cues) {
  const srt = []
  const vtt = ['WEBVTT', '']
  cues.forEach((cue, index) => {
    const start = cue.start
    const end = cue.start + cue.seconds
    srt.push(String(index + 1), `${stamp(start)} --> ${stamp(end)}`, cue.narration, '')
    vtt.push(`${stamp(start).replace(',', '.')} --> ${stamp(end).replace(',', '.')}`, cue.narration, '')
  })
  fs.writeFileSync(path.join(outDir, `${NAME}.srt`), srt.join('\n'), 'utf8')
  fs.writeFileSync(path.join(outDir, `${NAME}.vtt`), vtt.join('\n'), 'utf8')
}

// Same column order as ScriptToVideo slides.csv, so the narration can be reused with that tool.
function writeCsv() {
  const q = (value) => `"${String(value).replace(/"/g, '""')}"`
  const rows = ['Slide,Module,action,expected_result,verification_status,image,screenshot,voice_text,subtitle_text,visual_instruction']
  scenes.forEach((scene, index) => {
    const n = String(index + 1).padStart(2, '0')
    rows.push(
      [index + 1, q(scene.chapter.replace(/^Chapter \d+ — /, '')), q(scene.actions), q(scene.expected), 'VERIFIED', `${n}.png`, '', q(scene.narration), q(scene.title), q(scene.actions)].join(','),
    )
  })
  fs.writeFileSync(path.join(outDir, `${NAME}.csv`), rows.join('\n') + '\n', 'utf8')
}

async function mux(webm, cues, destination) {
  const videoSeconds = await probeDuration(webm)
  const last = cues[cues.length - 1]
  const audioEnd = last.start + last.seconds + 0.4
  const total = Math.max(videoSeconds, audioEnd)
  const extra = Math.max(0, audioEnd - videoSeconds)
  const filter = []
  const inputs = ['-y', '-i', webm]
  cues.forEach((cue, index) => {
    inputs.push('-i', cue.wav)
    const delay = Math.round(Math.max(0, cue.start) * 1000)
    filter.push(`[${index + 1}:a]adelay=${delay}|${delay},apad=pad_dur=0.2,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a${index}]`)
  })
  filter.push(`${cues.map((_, index) => `[a${index}]`).join('')}amix=inputs=${cues.length}:duration=longest:dropout_transition=0:normalize=0,atrim=0:${total.toFixed(3)},asetpts=PTS-STARTPTS[aout]`)
  filter.push(`[0:v]${extra > 0.05 ? `tpad=stop_mode=clone:stop_duration=${extra.toFixed(3)}` : 'null'},format=yuv420p[vout]`)
  await run('ffmpeg', [...inputs, '-filter_complex', filter.join(';'), '-map', '[vout]', '-map', '[aout]', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', destination])
  return probeDuration(destination)
}

async function extractFrames(file, cues) {
  fs.mkdirSync(frameDir, { recursive: true })
  for (let index = 0; index < cues.length; index += 1) {
    const at = Math.max(0.4, cues[index].start + Math.min(cues[index].seconds * 0.7, 6))
    await run('ffmpeg', ['-y', '-ss', at.toFixed(2), '-i', file, '-frames:v', '1', '-q:v', '3', path.join(frameDir, `${String(index + 1).padStart(2, '0')}.jpg`)])
  }
}

async function launchBrowser() {
  let lastError = new Error('No browser could be launched.')
  for (const options of [{ channel: 'chrome' }, { channel: 'msedge' }, {}]) {
    try {
      return await chromium.launch({ headless: true, slowMo: 60, ...options })
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error))
    }
  }
  throw lastError
}

async function main() {
  ensureSpeechScript()
  const prepared = []
  for (const scene of scenes) {
    const wav = await synthesize(scene.narration)
    prepared.push({ ...scene, wav, seconds: await probeDuration(wav) })
  }
  const browser = await launchBrowser()
  const context = await browser.newContext({
    viewport: { width: 1600, height: 900 },
    locale: 'en-US',
    timezoneId: 'Asia/Kolkata',
    colorScheme: 'light',
    recordVideo: { dir: workDir, size: { width: 1600, height: 900 } },
  })
  const page = await context.newPage()
  page.setDefaultTimeout(30000)
  page.setDefaultNavigationTimeout(30000)
  const t0 = performance.now()
  const cues = []
  const video = page.video()
  try {
    for (let index = 0; index < prepared.length; index += 1) {
      const scene = prepared[index]
      console.log(`scene ${index + 1}/${prepared.length} ${scene.title}`)
      const start = (performance.now() - t0) / 1000
      cues.push({ start, seconds: scene.seconds, narration: scene.narration, wav: scene.wav })
      await scene.run(page)
      await assertNoSecret(page)
      const elapsed = (performance.now() - t0) / 1000 - start
      await page.waitForTimeout(Math.max(scene.seconds + 0.45 - elapsed, 2.5) * 1000)
    }
    await page.waitForTimeout(600)
  } catch (error) {
    fs.mkdirSync(frameDir, { recursive: true })
    await page.screenshot({ path: path.join(frameDir, 'failure.jpg') }).catch(() => {})
    throw error
  } finally {
    await context.close()
    await browser.close()
  }
  const webm = await video.path()
  const destination = path.join(outDir, `${NAME}.mp4`)
  const duration = await mux(webm, cues, destination)
  fs.rmSync(webm, { force: true })
  writeSubtitles(cues)
  writeCsv()
  await extractFrames(destination, cues)
  console.log(JSON.stringify({ file: destination, duration: Number(duration.toFixed(1)), scenes: cues.length }, null, 2))
}

main().catch((error) => {
  console.error(redact(error))
  process.exit(1)
})
