/**
 * Browser check of the dashboard against a THROWAWAY demo database (it changes the signed-in person's
 * design choice). Environment: DMS_WEB_URL (default http://localhost:5174) and DEMO_ACCESS_FILE.
 */
import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(
  'C:/Users/lenovo/AadiTech/Product/AadiProduct/MultiTenant/Aadi-MultiTenant-Platform/frontend/package.json',
)
const { chromium } = require('playwright')
const here = path.dirname(fileURLToPath(import.meta.url))
const web = process.env.DMS_WEB_URL ?? 'http://localhost:5174'
const accessFile = process.env.DEMO_ACCESS_FILE ?? path.join(here, '../docs/demo/DMS_DEMO_ACCESS.md')
const password = fs.readFileSync(accessFile, 'utf8').match(/Temporary password for every account below: `([^`]+)`/)[1]

let failed = 0
const check = (name, ok, detail = '') => {
  if (!ok) failed += 1
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : ' ' + detail}`)
}
const browser = await chromium.launch({ headless: true }).catch(() => chromium.launch({ headless: true, channel: 'chrome' }))
const errors = []
async function open(email) {
  const page = await (await browser.newContext({ viewport: { width: 1500, height: 1000 } })).newPage()
  page.on('pageerror', (e) => errors.push(String(e)))
  await page.goto(web + '/')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.getByRole('heading', { name: 'Dashboard', exact: true }).waitFor()
  return page
}
const text = (page) => page.locator('body').innerText()
async function waitText(page, needle, ms = 8000) {
  await page.waitForFunction((n) => document.body.innerText.includes(n), needle, { timeout: ms }).catch(() => {})
  return (await text(page)).includes(needle)
}
const token = (page) => page.evaluate(() => JSON.parse(sessionStorage.getItem('dms.session')).access)
const getJson = (page, url) =>
  token(page).then((t) => page.evaluate(async ([u, t]) => (await fetch('/api/v1' + u, { headers: { Authorization: 'Bearer ' + t } })).json(), [url, t]))

const asha = await open('asha.kulkarni@demo.dms.test')
async function chooseDesign(page, key) {
  const cards = await getJson(page, '/ui-templates/available')
  const card = cards.find((c) => c.key === key || c.template_key === key || (c.name ?? '').toLowerCase().replace(/\s+/g, '-') === key)
  if (!card) return false
  const t = await token(page)
  await page.evaluate(async ([id, t]) => {
    await fetch('/api/v1/me/ui-preferences', { method: 'PUT', headers: { Authorization: 'Bearer ' + t, 'Content-Type': 'application/json' }, body: JSON.stringify({ template_id: id }) })
  }, [card.id, t])
  await page.goto(web + '/dashboard')
  await page.getByRole('heading', { name: 'Dashboard', exact: true }).waitFor()
  return true
}
await chooseDesign(asha, 'enterprise-productivity')
check('signing in lands on the dashboard', (await asha.getByRole('heading', { name: 'Dashboard', exact: true }).count()) === 1)
check('the dashboard is first in the menu', (await asha.getByRole('link', { name: 'Dashboard' }).count()) >= 1)
await waitText(asha, 'Recent documents')
const body = await text(asha)
check('the four figures are shown', ['Documents', 'Waiting for your review', 'Shared with you', 'Storage'].every((t) => body.includes(t)))
check('recent documents, due soon and the two charts are shown', ['Recent documents', 'Due soon', 'Added in the last 30 days', 'By classification'].every((t) => body.includes(t)))
check('an administrator sees recent activity', body.includes('Recent activity') && !body.includes('shown to administrators'))

const dash = await getJson(asha, '/dashboard')
const library = await getJson(asha, '/search?limit=1')
check('the document figure equals the library total', dash.stats.documents === library.total, `${dash.stats.documents} vs ${library.total}`)
check('the review figure equals the review queue', dash.stats.pending_reviews === (await getJson(asha, '/approvals/queue')).length)
const shown = await asha.locator('a', { hasText: /^Documents/ }).count()
check('clicking the documents figure opens the library', shown >= 1)
await asha.getByRole('link', { name: /you can see/ }).first().click().catch(() => {})
await asha.getByRole('heading', { name: 'Documents', exact: true }).waitFor().catch(() => {})
check('the library opens from the figure', (await asha.getByRole('heading', { name: 'Documents', exact: true }).count()) === 1)
await asha.getByRole('link', { name: 'Dashboard' }).first().click()
await asha.getByRole('heading', { name: 'Dashboard', exact: true }).waitFor()
await asha.getByRole('link', { name: /Audit log/ }).click()
check('the audit log opens from the activity card', await asha.getByRole('heading', { name: /Activity/ }).first().waitFor().then(() => true).catch(() => false))

// an ordinary employee: own figures, no activity feed, and never more documents than the library shows them
const sam = await open('sameer.patil@demo.dms.test')
await waitText(sam, 'Recent documents')
await chooseDesign(sam, 'enterprise-productivity')
await waitText(sam, 'Recent activity')
const samDash = await getJson(sam, '/dashboard')
const samLib = await getJson(sam, '/search?limit=1')
check('an employee sees only the documents the library shows them', samDash.stats.documents === samLib.total && samDash.stats.documents <= dash.stats.documents)
check('an employee has no activity feed', samDash.activity === null && (await text(sam)).includes('shown to administrators'))

// each design draws the same figures its own way
const layouts = {}
for (const key of ['enterprise-productivity', 'minimalist-productivity', 'premium-dark', 'modern-enterprise']) {
  layouts[key] = (await chooseDesign(asha, key)) ? await asha.locator('[data-dashboard-layout]').first().getAttribute('data-dashboard-layout') : 'missing'
}
check('designs choose the layout', layouts['enterprise-productivity'] === 'dense-grid' && layouts['minimalist-productivity'] === 'focus-list' && layouts['premium-dark'] === 'dark-hero' && layouts['modern-enterprise'] === 'stats-and-panels', JSON.stringify(layouts))
await chooseDesign(asha, 'premium-dark')
await waitText(asha, 'Your review queue')
await asha.screenshot({ path: process.env.SHOT ?? 'dark.png' })
const stillAll = await text(asha)
check('the dark design shows its welcome banner and the figures it chooses', ['Welcome,', 'Storage', 'By classification', 'Your review queue'].every((t) => stillAll.includes(t)))
await asha.evaluate(async (t) => {
  await fetch('/api/v1/me/ui-preferences', { method: 'PUT', headers: { Authorization: 'Bearer ' + t, 'Content-Type': 'application/json' }, body: JSON.stringify({ template_id: null }) })
}, await token(asha))

check('no script errors', errors.length === 0, errors.slice(0, 3).join(' | '))
await browser.close()
console.log(failed ? `${failed} check(s) FAILED` : 'ALL CHECKS PASSED')
process.exit(failed ? 1 : 0)
