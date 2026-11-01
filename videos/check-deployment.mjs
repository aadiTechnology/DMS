/**
 * Browser check of a DEPLOYED stack (the Coolify compose file run locally or on a server) through its one public
 * address. It changes data in that stack. Environment: DMS_STACK_URL (default http://localhost:8088) and
 * DMS_FIRST_LINK (the one-time link printed by `python -m app.provision create-org ...`).
 */
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(
  'C:/Users/lenovo/AadiTech/Product/AadiProduct/MultiTenant/Aadi-MultiTenant-Platform/frontend/package.json',
)
const { chromium } = require('playwright')
const here = path.dirname(fileURLToPath(import.meta.url))
const web = process.env.DMS_STACK_URL ?? 'http://localhost:8088'
const link = process.env.DMS_FIRST_LINK
if (!link) throw new Error('Set DMS_FIRST_LINK to the one-time link from `python -m app.provision create-org`')
const email = process.env.DMS_FIRST_EMAIL ?? 'owner@stacktest.example'
const password = 'Stack-Check-Passphrase-2026'
const pdf = path.join(here, 'assets', 'Service Agreement - Globex Logistics.pdf')

let failed = 0
const check = (name, ok, detail = '') => {
  if (!ok) failed += 1
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : ' ' + detail}`)
}
const browser = await chromium.launch({ headless: true }).catch(() => chromium.launch({ headless: true, channel: 'chrome' }))
const page = await (await browser.newContext({ viewport: { width: 1500, height: 1000 } })).newPage()
const errors = []
page.on('pageerror', (e) => errors.push(String(e)))
const text = () => page.locator('body').innerText()
async function waitText(needle, ms = 10000) {
  await page.waitForFunction((n) => document.body.innerText.includes(n), needle, { timeout: ms }).catch(() => {})
  return (await text()).includes(needle)
}

// the one public address serves the pages, the API and security headers
const home = await fetch(web + '/')
check('the web address serves the application', home.status === 200 && (await home.text()).includes('<div id="root">'))
check('security headers are sent', home.headers.get('x-content-type-options') === 'nosniff' && home.headers.get('x-frame-options') === 'DENY')
check('the API answers through the same address', (await (await fetch(web + '/api/v1/health')).json()).status === 'ok')
check('a deep link opens the application instead of an error', (await fetch(web + '/documents/00000000-0000-0000-0000-000000000000')).status === 200)
check('unknown API calls are refused, not served pages', (await fetch(web + '/api/v1/nothing')).status === 404)
const apiDirect = await fetch(web.replace(/:\d+$/, ':8000') + '/api/v1/health').then(() => true).catch(() => false)
check('the API is not reachable except through the web address', apiDirect === false)

// first administrator: one-time link, choose a password, sign in
await page.goto(link)
await page.getByLabel('New password', { exact: true }).fill(password)
await page.getByLabel('Repeat password').fill(password)
await page.getByRole('button', { name: 'Save password' }).click()
check('the one-time link lets the administrator choose a password', await waitText('Your password was changed'))
await page.getByLabel('Email').fill(email)
await page.getByLabel('Password').fill(password)
await page.getByRole('button', { name: 'Sign in' }).click()
await page.getByRole('heading', { name: 'Dashboard', exact: true }).waitFor()
check('the administrator signs in and sees the dashboard', true)
check('the sign-in link works only once', (await fetch(web + '/api/v1/auth/reset-password', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: new URL(link).searchParams.get('token'), password: 'Another-Passphrase-2026' }) })).status === 400)

// a reload on a deep page keeps the person signed in and shows the page
await page.getByRole('link', { name: 'Categories' }).click()
await page.getByRole('heading', { name: 'Categories and tags' }).waitFor()
await page.reload()
check('reloading a page keeps the person on it', await page.getByRole('heading', { name: 'Categories and tags' }).waitFor().then(() => true).catch(() => false))

// the stack stores and reads a document end to end
await page.getByRole('button', { name: 'New category' }).click()
await page.getByRole('textbox', { name: /^Name/ }).fill('General')
await page.getByRole('button', { name: 'Create category' }).click()
await waitText('General')
await page.getByRole('link', { name: 'Upload' }).click()
await page.getByLabel(/^Category/).click()
await page.getByRole('option', { name: /General/ }).click()
await page.getByLabel('File', { exact: true }).setInputFiles(pdf)
await page.getByRole('button', { name: 'Upload', exact: true }).click()
check('a document uploads through the proxy', await waitText('Service Agreement', 20000) || (await page.url()).includes('/documents/'))
await page.getByRole('link', { name: 'Documents' }).first().click()
check('and appears in the library', await waitText('Service Agreement'))
await page.getByRole('link', { name: /Service Agreement/ }).first().click()
await page.getByRole('button', { name: /Preview/ }).first().click().catch(() => {})
check('the document page opens', await waitText('Version'))

check('no script errors', errors.length === 0, errors.slice(0, 3).join(' | '))
await browser.close()
console.log(failed ? `${failed} check(s) FAILED` : 'ALL CHECKS PASSED')
process.exit(failed ? 1 : 0)
