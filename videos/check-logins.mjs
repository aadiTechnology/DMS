/**
 * Browser login check for the demo accounts: signs in as each role through the real sign-in page,
 * confirms the library loads, then signs out. Prints PASS or FAIL per account, never the password.
 * Needs the demo API (8000), the web app (5173) and docs/demo/DMS_DEMO_ACCESS.md.
 */
import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(
  'C:/Users/lenovo/AadiTech/Product/AadiProduct/MultiTenant/Aadi-MultiTenant-Platform/frontend/package.json',
)
const { chromium } = require('playwright')
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const access = fs.readFileSync(path.join(repo, 'docs/demo/DMS_DEMO_ACCESS.md'), 'utf8')
const password = access.match(/Temporary password for every account below: `([^`]+)`/)?.[1]
if (!password) throw new Error('Demo password not found')
const emails = [...access.matchAll(/`([a-z.]+@demo\.dms\.test)`/g)].map((m) => m[1])

let failed = 0
const browser = await chromium.launch({ headless: true }).catch(() => chromium.launch({ headless: true, channel: 'chrome' }))
for (const email of emails) {
  const page = await (await browser.newContext({ viewport: { width: 1400, height: 800 } })).newPage()
  try {
    await page.goto('http://localhost:5173/')
    await page.getByLabel('Email').fill(email)
    await page.getByLabel('Password').fill(password)
    await page.getByRole('button', { name: 'Sign in' }).click()
    await page.getByRole('heading', { name: 'Documents', exact: true }).waitFor({ timeout: 15000 })
    await page.getByText(email).waitFor()
    await page.getByRole('table').waitFor()
    await page.getByRole('button', { name: 'Sign out' }).click()
    await page.getByRole('button', { name: 'Sign in' }).waitFor()
    console.log(`PASS ${email}`)
  } catch (error) {
    failed += 1
    console.log(`FAIL ${email}: ${String(error.message).split(password).join('[redacted]').split('\n')[0]}`)
  }
}
await browser.close()
process.exit(failed ? 1 : 0)
