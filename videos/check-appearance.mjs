/**
 * Browser acceptance check for the design (template) feature, run against a THROWAWAY demo database:
 *   - each person chooses and previews their own design; two people in one organization differ
 *   - the choice persists across sessions and across a second browser (another device)
 *   - invalid design files are rejected; a sixth design is imported and published by a platform
 *     administrator and appears for others with no rebuild or redeployment
 *   - ordinary people have no catalogue screen; reset returns to the default
 * It publishes a sixth design, so it needs a fresh database each time. Environment:
 *   DMS_WEB_URL (default http://localhost:5174) and DEMO_ACCESS_FILE (path of the access file).
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
const repo = path.resolve(here, '..')
const web = process.env.DMS_WEB_URL ?? 'http://localhost:5174'
const accessFile = process.env.DEMO_ACCESS_FILE ?? path.join(repo, 'docs/demo/DMS_DEMO_ACCESS.md')
const password = fs.readFileSync(accessFile, 'utf8').match(/Temporary password for every account below: `([^`]+)`/)[1]
const sixth = path.join(here, 'assets/sixth-template-forest.json')
const invalid = path.join(here, 'assets/invalid-template.json')

let failed = 0
const check = (name, ok, detail = '') => {
  if (!ok) failed += 1
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : ' ' + detail}`)
}

const browser = await chromium.launch({ headless: true }).catch(() => chromium.launch({ headless: true, channel: 'chrome' }))
const errors = []

async function open(email) {
  const context = await browser.newContext({ viewport: { width: 1500, height: 900 } })
  const page = await context.newPage()
  page.on('pageerror', (e) => errors.push(String(e)))
  await page.goto(web + '/')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.getByRole('heading', { name: /^(Dashboard|Documents)$/ }).waitFor()
  if (await page.getByRole('heading', { name: 'Dashboard', exact: true }).count()) { await page.getByRole('link', { name: 'Documents' }).first().click(); await page.getByRole('heading', { name: 'Documents', exact: true }).waitFor() }
  return { context, page }
}
const design = (page) => page.locator('[data-dms-template]').first().getAttribute('data-dms-template')
async function waitDesign(page, key) {
  await page.waitForFunction((k) => document.querySelector('[data-dms-template]')?.getAttribute('data-dms-template') === k, key, { timeout: 8000 }).catch(() => {})
  return design(page)
}
/** True once the locator matches exactly n elements (the page loads lists after it first appears). */
async function countIs(locator, n, ms = 6000) {
  const end = Date.now() + ms
  while (Date.now() < end) {
    if ((await locator.count()) === n) return true
    await new Promise((r) => setTimeout(r, 150))
  }
  return (await locator.count()) === n
}
const goto = async (page, p, heading) => {
  await page.getByRole('link', { name: p }).click()
  await page.getByRole('heading', { name: heading }).first().waitFor()
}

// 1. Sameer previews, stops, applies Premium Dark
const sam = await open('sameer.patil@demo.dms.test')
check('a new user starts on the product default design', (await design(sam.page)) === 'modern-enterprise')
await goto(sam.page, 'Appearance', 'Choose your design')
await sam.page.getByTestId('design-premium-dark').waitFor()
check('five designs are offered with previews', (await countIs(sam.page.locator('[data-testid^="design-"]'), 5)) && (await countIs(sam.page.getByTestId('template-thumbnail'), 5)))
await sam.page.getByTestId('design-premium-dark').getByRole('button', { name: 'Preview' }).click()
check('preview restyles the app without saving', (await waitDesign(sam.page, 'premium-dark')) === 'premium-dark')
await sam.page.getByRole('button', { name: 'Stop previewing' }).first().click()
check('stopping the preview restores the design', (await waitDesign(sam.page, 'modern-enterprise')) === 'modern-enterprise')
await sam.page.getByTestId('design-premium-dark').getByRole('button', { name: 'Select' }).click()
check('applying changes the design at once', (await waitDesign(sam.page, 'premium-dark')) === 'premium-dark')
await sam.page.getByTestId('design-premium-dark').getByText('Selected').first().waitFor()
await goto(sam.page, 'Documents', 'Documents')
check('the design stays while moving between pages', (await design(sam.page)) === 'premium-dark')

// 2. Neha, same organization, has her own design
const neha = await open('neha.shah@demo.dms.test')
check('a colleague in the same organization is not affected', (await design(neha.page)) === 'modern-enterprise')
await goto(neha.page, 'Appearance', 'Choose your design')
await neha.page.getByTestId('design-modern-saas').getByRole('button', { name: 'Select' }).click()
check('the colleague chooses a different design', (await waitDesign(neha.page, 'modern-saas')) === 'modern-saas')
await sam.page.reload()
check('the first person still has theirs', (await waitDesign(sam.page, 'premium-dark')) === 'premium-dark')

// 3. A second browser (another device) shows the same choice immediately
const samElsewhere = await open('sameer.patil@demo.dms.test')
check('the choice follows the person to another device', (await waitDesign(samElsewhere.page, 'premium-dark')) === 'premium-dark')
await samElsewhere.context.close()

// 4. Ordinary people cannot manage the catalogue
check('no catalogue screen for ordinary people', (await sam.page.getByRole('link', { name: 'Design catalogue' }).count()) === 0)
await sam.page.goto(web + '/platform/designs')
await sam.page.getByText(/administrator access required/i).waitFor()
check('the catalogue is closed to them even by address', true)

// 5. The platform administrator rejects a bad file, then imports and publishes a sixth design
const admin = await open('asha.kulkarni@demo.dms.test')
await goto(admin.page, 'Design catalogue', 'Design catalogue')
await admin.page.getByLabel('Design file').setInputFiles(invalid)
await admin.page.getByText('This file cannot be used.').waitFor()
check('an unsafe file is rejected and cannot be saved', (await admin.page.getByRole('button', { name: 'Save as draft' }).isDisabled()) && (await admin.page.getByRole('button', { name: 'Save and publish' }).isDisabled()))
await admin.page.getByLabel('Design file').setInputFiles(sixth)
await admin.page.getByText('Forest Calm').first().waitFor()
check('a valid file shows its name, description and version', (await admin.page.getByText('version 1.0.0').count()) > 0)
await admin.page.getByRole('button', { name: 'Save as draft' }).click()
await admin.page.getByText('Saved as a draft').waitFor()
await goto(sam.page, 'Appearance', 'Choose your design')
await sam.page.reload()
await sam.page.getByTestId('design-premium-dark').waitFor()
check('a draft is invisible to other people', (await countIs(sam.page.locator('[data-testid^="design-"]'), 5, 3000)))
await admin.page.getByRole('row', { name: /Forest Calm/ }).getByRole('button', { name: 'Publish' }).click()
await admin.page.getByRole('row', { name: /Forest Calm/ }).getByText('Published').waitFor()
await sam.page.reload()
await sam.page.getByTestId('design-forest-calm').waitFor()
check('the sixth design appears after a plain reload, no rebuild or deployment', await countIs(sam.page.locator('[data-testid^="design-"]'), 6))
await sam.page.getByTestId('design-forest-calm').getByRole('button', { name: 'Select' }).click()
check('the sixth design can be applied', (await waitDesign(sam.page, 'forest-calm')) === 'forest-calm')

// 6. Reset
await sam.page.getByRole('button', { name: 'Reset to default' }).click()
check('reset returns to the default design', (await waitDesign(sam.page, 'modern-enterprise')) === 'modern-enterprise')
check('the colleague kept hers', (await design(neha.page)) === 'modern-saas')
check('no script errors in any page', errors.length === 0, errors.slice(0, 3).join(' | '))

await browser.close()
console.log(failed ? `${failed} check(s) FAILED` : 'ALL CHECKS PASSED')
process.exit(failed ? 1 : 0)
