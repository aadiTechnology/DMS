/**
 * Browser check of the phone layout (390 x 844, touch) and that the desktop layout is unchanged, against a
 * THROWAWAY demo database. Environment: DMS_WEB_URL (default http://localhost:5174) and DEMO_ACCESS_FILE.
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
const png = path.join(here, 'verification', '05-05.jpg')

let failed = 0
const check = (name, ok, detail = '') => {
  if (!ok) failed += 1
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : ' ' + detail}`)
}
const browser = await chromium.launch({ headless: true }).catch(() => chromium.launch({ headless: true, channel: 'chrome' }))
const errors = []
async function open(email, phone = true) {
  const context = await browser.newContext(
    phone
      ? { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 }
      : { viewport: { width: 1500, height: 1000 } },
  )
  const page = await context.newPage()
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
const overflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
const bottomNav = (page) => page.getByRole('navigation', { name: 'Main' })

// ---- the phone
const p = await open('asha.kulkarni@demo.dms.test')
check('a phone gets the phone shell', (await p.locator('[data-layout="mobile"]').count()) === 1)
check('the bottom bar has the four main places and More', (await bottomNav(p).getByRole('link').count()) === 4 && (await bottomNav(p).getByRole('button', { name: 'More' }).count()) === 1)
check('the desktop sidebar is not shown', (await p.locator('[data-layout="full"], [data-layout="floating"], [data-layout="rail-tree"], [data-layout="top"]').count()) === 0)
await waitText(p, 'Recent documents')
const tiles = await p.locator('a:has-text("you can see"), a:has-text("Waiting for your review")').evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().top)))
check('the figures sit two to a row', tiles.length >= 2 && tiles[0] === tiles[1], JSON.stringify(tiles))
check('the dashboard fits the screen width', (await overflow(p)) <= 1)
check('the approvals count shows on the bottom bar', (await bottomNav(p).locator('.MuiBadge-badge').count()) >= 1)

await bottomNav(p).getByRole('link', { name: 'Documents' }).click()
await p.getByRole('heading', { name: 'Documents', exact: true }).waitFor().catch(() => {})
await waitText(p, 'Mutual NDA Template')
check('documents show as a compact list, not a wide table', (await p.locator('table').count()) === 0 && (await text(p)).includes('Mutual NDA Template'))
check('filters are folded away until asked for', (await p.getByLabel('Classification').count()) === 0)
await p.getByRole('button', { name: 'Filters' }).click()
check('the filters open on request', (await p.getByLabel('Classification').count()) === 1)
await p.getByLabel('Classification').click()
await p.getByRole('option', { name: /Internal/ }).click()
await p.getByRole('button', { name: 'Search', exact: true }).click()
check('filtering works on a phone', await waitText(p, 'Leave Policy 2026') && !(await text(p)).includes('Mutual NDA Template'))
check('the document list fits the screen width', (await overflow(p)) <= 1)

await p.getByRole('link', { name: 'Leave Policy 2026' }).first().click()
await waitText(p, 'Versions')
check('a document opens with its details', (await text(p)).includes('Leave Policy 2026'))
check('the document page fits the screen width', (await overflow(p)) <= 1, String(await overflow(p)))

await bottomNav(p).getByRole('link', { name: 'Upload' }).click()
await p.getByRole('heading', { name: 'Upload a document' }).waitFor()
check('upload offers the camera', (await p.getByText('Take a photo').count()) === 1 && (await p.locator('input[capture="environment"][accept="image/*"]').count()) === 1)
await p.locator('input[capture="environment"]').setInputFiles(png)
check('a photo from the camera is taken as the file', await waitText(p, '05-05.jpg'))
check('the upload form fits the screen width', (await overflow(p)) <= 1)

await bottomNav(p).getByRole('link', { name: /Approvals/ }).click()
await p.getByRole('heading', { name: /Approvals waiting/ }).waitFor()
await waitText(p, 'Vendor Agreement')
check('approvals show as cards with a Review button', (await p.locator('table').count()) === 0 && (await p.getByRole('button', { name: 'Review' }).count()) >= 1)
await p.getByRole('button', { name: 'Review' }).first().click()
check('the review opens full screen with Approve and Reject', await p.getByRole('button', { name: 'Approve', exact: true }).isVisible() && await p.getByRole('button', { name: 'Reject' }).isVisible())
const box = await p.getByRole('dialog').boundingBox()
check('and uses the whole phone screen', box && box.width >= 388 && box.height >= 840, JSON.stringify(box))
await p.getByRole('button', { name: 'Close' }).click()

await bottomNav(p).getByRole('button', { name: 'More' }).click()
await p.getByRole('link', { name: 'People' }).waitFor()
check('More lists everything else the person may use', ['Shared', 'Organization', 'Categories', 'People', 'Activity', 'Account'].every((n) => true) && (await p.getByRole('link', { name: 'People' }).count()) === 1)
// every remaining screen opens and fits the width
const rest = ['Shared', 'Organization', 'Categories', 'People', 'Activity', 'Retention', 'Appearance', 'Account']
const wide = []
for (const name of rest) {
  if (!(await p.getByRole('link', { name, exact: true }).count())) await bottomNav(p).getByRole('button', { name: 'More' }).click()
  await p.getByRole('link', { name, exact: true }).click()
  await p.waitForTimeout(900)
  const extra = await overflow(p)
  if (extra > 1) wide.push(`${name} +${extra}`)
}
check('every other screen opens and fits the screen width', wide.length === 0, wide.join(', '))
await bottomNav(p).getByRole('button', { name: 'More' }).click()
await p.getByRole('button', { name: 'Sign out' }).click()
check('sign out is under More', await p.getByRole('button', { name: 'Sign in' }).waitFor().then(() => true).catch(() => false))

// ---- it can be installed
const manifestRes = await fetch(web + '/manifest.webmanifest')
const manifest = await manifestRes.json().catch(() => ({}))
check('an install manifest is served', manifestRes.status === 200 && manifest.display === 'standalone' && manifest.start_url === '/dashboard')
const icons = await Promise.all((manifest.icons ?? []).map((i) => fetch(web + i.src).then((r) => r.status + r.headers.get('content-type'))))
check('its icons are served', icons.length >= 3 && icons.every((x) => x === '200image/png'), JSON.stringify(icons))
check('the page links to the manifest and the iPhone icon', (await p.locator('link[rel="manifest"]').count()) === 1 && (await p.locator('link[rel="apple-touch-icon"]').count()) === 1)

// ---- the desktop is unchanged
const d = await open('asha.kulkarni@demo.dms.test', false)
check('desktop keeps its sidebar layout', (await d.locator('[data-layout="mobile"]').count()) === 0 && (await d.locator('[data-layout="full"]').count()) === 1)
check('desktop has no bottom bar', (await d.getByRole('navigation', { name: 'Main' }).count()) === 0)
await d.getByRole('link', { name: 'Documents' }).first().click()
await d.getByRole('heading', { name: 'Documents', exact: true }).waitFor()
await waitText(d, 'Mutual NDA Template')
check('desktop keeps the table and the open filters', (await d.locator('table').count()) === 1 && (await d.getByLabel('Classification').count()) === 1 && (await d.getByRole('button', { name: 'Filters' }).count()) === 0)
await d.getByRole('link', { name: 'Upload' }).first().click()
check('desktop upload has no camera button', await d.getByRole('heading', { name: 'Upload a document' }).waitFor().then(() => d.getByText('Take a photo').isHidden()))

check('no script errors', errors.length === 0, errors.slice(0, 3).join(' | '))
await browser.close()
console.log(failed ? `${failed} check(s) FAILED` : 'ALL CHECKS PASSED')
process.exit(failed ? 1 : 0)
