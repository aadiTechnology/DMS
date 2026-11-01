/**
 * Browser check of the administration screens (People: roles, invitations, join requests, two-step
 * reset; Activity: audit log and search index) against a THROWAWAY demo database. It changes data.
 * Environment: DMS_WEB_URL (default http://localhost:5174), DEMO_ACCESS_FILE.
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
  const context = await browser.newContext({ viewport: { width: 1500, height: 950 } })
  const page = await context.newPage()
  page.on('pageerror', (e) => errors.push(String(e)))
  await page.goto(web + '/')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.getByRole('heading', { name: /^(Dashboard|Documents)$/ }).waitFor()
  if (await page.getByRole('heading', { name: 'Dashboard', exact: true }).count()) { await page.getByRole('link', { name: 'Documents' }).first().click(); await page.getByRole('heading', { name: 'Documents', exact: true }).waitFor() }
  return page
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

const asha = await open('asha.kulkarni@demo.dms.test')
const sam = await open('sameer.patil@demo.dms.test')
check('ordinary employees have no People or Activity screens', (await sam.getByRole('link', { name: 'People' }).count()) === 0 && (await sam.getByRole('link', { name: 'Activity' }).count()) === 0)

// People and roles
await asha.getByRole('link', { name: 'People' }).click()
await asha.getByRole('heading', { name: 'People' }).waitFor()
check('the employee list shows people with their roles', (await waitText(asha, 'Neha Shah')) && (await waitText(asha, 'Organization Administrator')) || (await waitText(asha, 'org_admin')))
const nehaRow = () => asha.getByRole('row', { name: /Neha Shah/ })
await nehaRow().getByRole('button', { name: 'Roles' }).click()
await asha.getByRole('checkbox', { name: /Reviewer/ }).click()
await asha.waitForTimeout(900)
await asha.getByRole('dialog').getByRole('button', { name: 'Close' }).last().click()
check('a role can be given to someone', await waitText(asha, 'Reviewer / approver') || (await nehaRow().innerText()).toLowerCase().includes('reviewer'))
await nehaRow().getByRole('button', { name: 'Roles' }).click()
await asha.getByRole('checkbox', { name: /Reviewer/ }).click()
await asha.waitForTimeout(900)
await asha.getByRole('dialog').getByRole('button', { name: 'Close' }).last().click()
check('and taken away again', await gone(asha, 'Reviewer / approver') || !(await nehaRow().innerText()).toLowerCase().includes('reviewer'))

// The last administrator cannot be removed
await asha.getByRole('row', { name: /Asha Kulkarni/ }).getByRole('button', { name: 'Roles' }).click()
await asha.getByRole('checkbox', { name: /Organization administrator|org_admin/i }).click()
await asha.waitForTimeout(900)
check('the last administrator cannot be removed', await waitText(asha, 'at least one administrator'))
await asha.getByRole('dialog').getByRole('button', { name: 'Close' }).last().click()

// Two-step reset
await nehaRow().getByRole('button', { name: 'Reset two-step' }).click()
await asha.getByRole('button', { name: 'Reset two-step verification', exact: true }).click()
check('two-step verification can be reset for someone who lost a device', await waitText(asha, 'Two-step verification was reset.'))

// Invitations
await asha.getByRole('button', { name: 'Invite someone' }).click()
await asha.getByLabel('Work email').fill('new.person@aaditech.in')
await asha.getByLabel('Full name').fill('New Person')
await asha.getByRole('button', { name: 'Send invitation' }).click()
await asha.getByRole('tab', { name: /Invitations/ }).click()
check('an invitation is sent and listed', await waitText(asha, 'New Person'))
await asha.getByRole('row', { name: /New Person/ }).getByRole('button', { name: 'Resend' }).click()
check('it can be sent again', await waitText(asha, 'sent again'))
await asha.getByRole('row', { name: /New Person/ }).getByRole('button', { name: 'Withdraw' }).click()
check('and withdrawn', await gone(asha, 'New Person'))

// Join requests
await asha.getByRole('tab', { name: /Join requests/ }).click()
await asha.getByRole('checkbox', { name: /Let people ask to join/ }).click()
await asha.waitForTimeout(900)
await asha.waitForTimeout(800)
const registered = await asha.evaluate(async () => (await fetch('/api/v1/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tenant_slug: 'demo-industries', email: 'walk.in@aaditech.in', full_name: 'Walk In' }) })).status)
check('self-registration can be switched on and a request arrives', registered === 202)
await asha.reload()
await asha.getByRole('tab', { name: /Join requests/ }).click()
check('the request waits for a decision', await waitText(asha, 'Walk In'))
await asha.getByRole('row', { name: /Walk In/ }).getByRole('button', { name: 'Approve and invite' }).click()
check('approving sends an invitation', await waitText(asha, 'Approved. An invitation was sent.'))

// Activity
await asha.getByRole('link', { name: 'Activity' }).click()
await asha.getByRole('heading', { name: 'Activity' }).waitFor()
check('the audit log lists what happened, with names', (await waitText(asha, 'Asha Kulkarni')) && (await text(asha)).includes('invitation'))
await asha.getByLabel(/Action \(exact/).fill('document.uploaded')
await asha.getByRole('button', { name: 'Filter' }).click()
check('the log can be filtered by action', (await waitText(asha, 'document.uploaded')) && (await gone(asha, 'invitation.')))
await asha.getByRole('tab', { name: 'Search index' }).click()
await asha.getByRole('button', { name: 'Process the queue now' }).click()
check('the search index can be checked and processed', (await waitText(asha, 'Processed the queue')) && (await text(asha)).includes('indexed'))

check('no script errors', errors.length === 0, errors.slice(0, 3).join(' | '))
await browser.close()
console.log(failed ? `${failed} check(s) FAILED` : 'ALL CHECKS PASSED')
process.exit(failed ? 1 : 0)
