/**
 * Browser check of the document actions (share, edit details, new version, restore, in-page
 * preview, stale-version protection) against a THROWAWAY demo database. It changes data, so
 * use a fresh database each time. Environment: DMS_WEB_URL (default http://localhost:5174) and
 * DEMO_ACCESS_FILE (path of the access file written when the database was seeded).
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
const pdf = path.join(here, 'assets', 'Service Agreement - Globex Logistics.pdf')

let failed = 0
const check = (name, ok, detail = '') => {
  if (!ok) failed += 1
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : ' ' + detail}`)
}
const browser = await chromium.launch({ headless: true }).catch(() => chromium.launch({ headless: true, channel: 'chrome' }))
const errors = []

async function open(email) {
  const context = await browser.newContext({ viewport: { width: 1500, height: 950 } })
  const page = await context.newPage()
  page.on('pageerror', (e) => errors.push(String(e)))
  await page.goto(web + '/')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.getByRole('heading', { name: 'Documents', exact: true }).waitFor()
  return { context, page }
}
async function openDoc(page, title) {
  await page.getByRole('link', { name: 'Documents' }).first().click()
  await page.getByRole('link', { name: title }).first().click()
  await page.getByTestId('doc-title').waitFor()
}
const text = (page) => page.locator('body').innerText()
async function waitText(page, needle, ms = 8000) {
  await page.waitForFunction((n) => document.body.innerText.includes(n), needle, { timeout: ms }).catch(() => {})
  return (await text(page)).includes(needle)
}

const sam = await open('sameer.patil@demo.dms.test')
const priya = await open('priya.nair@demo.dms.test')
await openDoc(sam.page, 'Invoice INV-1002 Northwind Logistics')

// Share and stop sharing
await sam.page.getByRole('button', { name: 'Share' }).click()
await sam.page.getByLabel('Colleague').fill('Priya')
await sam.page.getByRole('option', { name: /Priya Nair/ }).click()
await sam.page.getByLabel('Access').click()
await sam.page.getByRole('option', { name: 'View and download' }).click()
await sam.page.getByRole('dialog').getByRole('button', { name: 'Share', exact: true }).click()
check('a colleague is found by name and the document is shared', await waitText(sam.page, 'Priya Nair · view and download'))
await priya.page.getByRole('link', { name: 'Shared' }).click()
check('the colleague sees it in Shared with me', await waitText(priya.page, 'Invoice INV-1002 Northwind Logistics'))
await sam.page.getByRole('button', { name: 'Stop sharing' }).click()
check('stopping the share is shown', await waitText(sam.page, 'Not shared with anyone yet.'))
await priya.page.reload()
await priya.page.getByRole('link', { name: 'Shared' }).click()
await priya.page.getByText('Nothing has been shared with you.').waitFor().catch(() => {})
check('the colleague loses access at once', !(await text(priya.page)).includes('Invoice INV-1002 Northwind Logistics'))
await sam.page.getByRole('dialog').getByRole('button', { name: 'Close' }).click()

// Edit details
await sam.page.getByRole('button', { name: 'Edit details' }).click()
await sam.page.getByLabel('Title').fill('Invoice INV-1002 Northwind Logistics (paid)')
await sam.page.getByLabel('Vendor').fill('Northwind Logistics Ltd')
await sam.page.getByRole('button', { name: 'Save changes' }).click()
check('title and extra fields can be edited', (await waitText(sam.page, 'Invoice INV-1002 Northwind Logistics (paid)')) && (await waitText(sam.page, 'Northwind Logistics Ltd')))

// In-page preview: an Excel file has none
await sam.page.getByRole('button', { name: 'Preview' }).first().click()
check('a type without preview says so', await waitText(sam.page, 'This file type has no preview'))
await sam.page.getByRole('dialog').getByRole('button', { name: 'Close' }).click()

// New version, then in-page preview of a PDF
await sam.page.getByRole('button', { name: 'New version' }).click()
await sam.page.getByLabel('New version file').setInputFiles(pdf)
await sam.page.getByLabel('What changed (optional)').fill('Scanned copy')
await sam.page.getByRole('button', { name: 'Upload version' }).click()
check('a new version is uploaded', await waitText(sam.page, 'The new version was uploaded and scanned'))
await sam.page.getByRole('dialog').getByRole('button', { name: 'Done' }).click()
await waitText(sam.page, 'Scanned copy')
await sam.page.getByRole('row', { name: /v2/ }).getByText('Current').waitFor().catch(() => {})
check('the history shows version 2 as current', (await sam.page.getByRole('row', { name: /v2/ }).getByText('Current').count()) === 1)
await sam.page.getByRole('row', { name: /v2/ }).getByRole('button', { name: 'Preview' }).click()
await sam.page.locator('iframe[title="Document preview"]').waitFor()
check('a PDF opens inside the page', /^http/.test((await sam.page.locator('iframe[title="Document preview"]').getAttribute('src')) ?? ''))
await sam.page.getByRole('dialog').getByRole('button', { name: 'Close' }).click()

// Restore version 1
await sam.page.getByRole('row', { name: /v1/ }).getByRole('button', { name: 'Restore' }).click()
await sam.page.getByRole('row', { name: /v3/ }).first().waitFor().catch(() => {})
check('an old version is restored as a new version', (await waitText(sam.page, 'Version 1 was restored as a new version')) && (await sam.page.getByRole('row', { name: /v3/ }).count()) === 1)

// Stale protection: a second window adds version 4 while the first still shows version 3
const samB = await open('sameer.patil@demo.dms.test')
await openDoc(samB.page, 'Invoice INV-1002 Northwind Logistics (paid)')
await sam.page.getByRole('button', { name: 'New version' }).click()
await samB.page.getByRole('button', { name: 'New version' }).click()
await samB.page.getByLabel('New version file').setInputFiles(pdf)
await samB.page.getByRole('button', { name: 'Upload version' }).click()
await waitText(samB.page, 'The new version was uploaded')
await sam.page.getByLabel('New version file').setInputFiles(pdf)
await sam.page.getByRole('button', { name: 'Upload version' }).click()
check('a second person adding a version meanwhile is detected, nothing is overwritten', await waitText(sam.page, 'reload the document'))
await sam.page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click()

// Someone who sees the document but does not own it is refused by the server
const rohan = await open('rohan.deshmukh@demo.dms.test')
await openDoc(rohan.page, 'Invoice INV-1002 Northwind Logistics (paid)')
await rohan.page.getByRole('button', { name: 'Edit details' }).click()
await rohan.page.getByLabel('Title').fill('Changed by someone else')
await rohan.page.getByRole('button', { name: 'Save changes' }).click()
check('a non-owner cannot change the document', (await waitText(rohan.page, 'not found')) || (await waitText(rohan.page, 'denied')))
await rohan.page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click()
await rohan.page.reload()
check('and the title is unchanged', await waitText(rohan.page, 'Invoice INV-1002 Northwind Logistics (paid)'))

check('no script errors', errors.length === 0, errors.slice(0, 3).join(' | '))
await browser.close()
console.log(failed ? `${failed} check(s) FAILED` : 'ALL CHECKS PASSED')
process.exit(failed ? 1 : 0)
