/**
 * Browser check of review comments, resubmission, legal hold, deletion request and approval,
 * the due-soon list and "Uploaded by me", against a THROWAWAY demo database (it changes data and
 * sets retention dates directly in the database to create the situations). Environment:
 * DMS_WEB_URL (default http://localhost:5174), DEMO_ACCESS_FILE, and PGDATABASE (the throwaway
 * database name, default dms_demo_w2).
 */
import { execFileSync } from 'node:child_process'
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
const db = process.env.PGDATABASE ?? 'dms_demo_w2'
const accessFile = process.env.DEMO_ACCESS_FILE ?? path.join(here, '../docs/demo/DMS_DEMO_ACCESS.md')
const password = fs.readFileSync(accessFile, 'utf8').match(/Temporary password for every account below: `([^`]+)`/)[1]
const sql = (q) => execFileSync('docker', ['exec', 'dms-postgres-1', 'psql', '-U', 'dms', '-d', db, '-q', '-c', q], { encoding: 'utf8' })

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
  return page
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
async function gone(page, needle, ms = 6000) {
  await page.waitForFunction((n) => !document.body.innerText.includes(n), needle, { timeout: ms }).catch(() => {})
  return !(await text(page)).includes(needle)
}

const sam = await open('sameer.patil@demo.dms.test')
const meera = await open('meera.joshi@demo.dms.test')
const asha = await open('asha.kulkarni@demo.dms.test')

// "Uploaded by me"
await sam.getByText('Leave Policy 2026').first().waitFor()
await sam.getByRole('button', { name: 'Uploaded by me' }).click()
check('"Uploaded by me" hides documents someone else uploaded', await gone(sam, 'Leave Policy 2026'))
check('and keeps his own', await waitText(sam, 'Invoice INV-1001'))

// Comments, rejection, resubmission
await openDoc(sam, 'Vendor Agreement - Acme Supplies')
await sam.getByLabel('Review comment').fill('The signed copy is attached to the ticket.')
await sam.getByRole('button', { name: 'Comment', exact: true }).click()
check('a comment is added to a review', await waitText(sam, 'The signed copy is attached to the ticket.'))
await meera.getByRole('link', { name: /Approvals/ }).click()
await meera.getByRole('row', { name: /Vendor Agreement - Acme Supplies/ }).getByRole('button', { name: 'Review' }).click()
await meera.getByLabel('Comment (required to reject)').fill('Missing the signature page.')
await meera.getByRole('button', { name: 'Reject', exact: true }).click()
await meera.getByRole('row', { name: /Vendor Agreement - Acme Supplies/ }).waitFor({ state: 'detached' }).catch(() => {})
await sam.reload()
await sam.getByTestId('doc-title').waitFor()
check('the submitter sees the rejection with its reason', (await waitText(sam, 'Missing the signature page.')) && (await waitText(sam, 'Rejected')))
await sam.getByRole('button', { name: 'Send for review again' }).click()
check('the document can be sent for review again', await waitText(sam, 'Sent for review again'))
check('earlier decisions stay on record', (await text(sam)).includes('Missing the signature page.'))

// Legal hold blocks deletion; release; request; approve
sql('UPDATE documents SET retention_until = current_date - 1')
await openDoc(asha, 'Invoice INV-1002 Northwind Logistics')
await asha.getByRole('button', { name: 'Place legal hold' }).click()
await asha.getByLabel('Reason').fill('Litigation 2026-14')
await asha.getByRole('button', { name: 'Place hold' }).click()
check('a legal hold is placed with its reason', await waitText(asha, 'Legal hold: Litigation 2026-14'))
await openDoc(sam, 'Invoice INV-1002 Northwind Logistics')
await sam.getByRole('button', { name: 'Request deletion' }).click()
await sam.getByLabel('Reason').fill('Duplicate of INV-1001')
await sam.getByRole('button', { name: 'Send request' }).click()
check('deletion is refused while a hold applies', await waitText(sam, 'legal hold'))
await sam.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click()
await asha.getByRole('button', { name: 'Release legal hold' }).click()
await asha.getByLabel('Reason').fill('Case closed')
await asha.getByRole('button', { name: 'Release hold' }).click()
check('the hold is released', await waitText(asha, 'No legal hold.'))
await sam.getByRole('button', { name: 'Request deletion' }).click()
await sam.getByLabel('Reason').fill('Duplicate of INV-1001')
await sam.getByRole('button', { name: 'Send request' }).click()
check('a deletion request is recorded', await waitText(sam, 'Deletion requested: “Duplicate of INV-1001”'))
check('ordinary employees have no retention screen', (await sam.getByRole('link', { name: 'Retention' }).count()) === 0)
await asha.getByRole('link', { name: 'Retention' }).click()
await asha.getByRole('tab', { name: /Deletion requests/ }).click()
await asha.getByRole('row', { name: /Invoice INV-1002/ }).getByRole('button', { name: 'Approve deletion' }).click()
await asha.getByRole('button', { name: 'Delete permanently' }).click()
check('the second person approves and the files are removed', await waitText(asha, 'Deleted. The stored files were removed'))
await sam.getByRole('link', { name: 'Documents' }).first().click()
check('the document is gone from lists', await gone(sam, 'Invoice INV-1002 Northwind Logistics'))

// Due soon
sql("UPDATE documents SET retention_until = current_date + 5 WHERE title = 'Mutual NDA Template'")
await asha.reload()
await asha.getByRole('tab', { name: 'Due soon' }).click()
check('documents nearing the end of retention are listed', (await waitText(asha, 'Mutual NDA Template')) && (await text(asha)).includes('Keep-until date approaching'))

check('no script errors', errors.length === 0, errors.slice(0, 3).join(' | '))
await browser.close()
console.log(failed ? `${failed} check(s) FAILED` : 'ALL CHECKS PASSED')
process.exit(failed ? 1 : 0)
