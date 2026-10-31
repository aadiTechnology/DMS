/**
 * Browser check of the categories, tags and organization editing screens against a THROWAWAY
 * demo database. It changes data. Environment: DMS_WEB_URL (default http://localhost:5174) and
 * DEMO_ACCESS_FILE.
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
  const context = await browser.newContext({ viewport: { width: 1500, height: 1000 } })
  const page = await context.newPage()
  page.on('pageerror', (e) => errors.push(String(e)))
  await page.goto(web + '/')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.getByRole('heading', { name: 'Documents', exact: true }).waitFor()
  return page
}
const text = (page) => page.locator('body').innerText()
async function waitText(page, needle, ms = 8000) {
  await page.waitForFunction((n) => document.body.innerText.includes(n), needle, { timeout: ms }).catch(() => {})
  return (await text(page)).includes(needle)
}
const pick = async (page, label, option) => {
  await page.getByLabel(label, { exact: true }).click()
  await page.getByRole('option', { name: option }).click()
}

const asha = await open('asha.kulkarni@demo.dms.test')
const sam = await open('sameer.patil@demo.dms.test')

// ordinary employees can read the organization but not change it
await sam.getByRole('link', { name: 'Organization' }).click()
await sam.getByRole('heading', { name: 'Organization' }).waitFor()
await waitText(sam, 'Finance')
check('an employee sees the organization with no editing controls', (await sam.getByRole('button', { name: 'Add' }).count()) === 0 && (await sam.getByRole('link', { name: 'Categories' }).count()) === 0)

// Categories
await asha.getByRole('link', { name: 'Categories' }).click()
await asha.getByRole('heading', { name: 'Categories and tags' }).waitFor()
check('categories are listed with their rules version', (await waitText(asha, 'Invoices')) && (await text(asha)).includes('v1'))
await asha.getByRole('button', { name: 'New category' }).click()
await asha.getByRole('textbox', { name: /^Name/ }).fill('HR Letters')
await asha.getByLabel('Default classification').click()
await asha.getByRole('option', { name: 'Confidential', exact: true }).click()
await asha.getByLabel('Documents are reviewed before they are released').click()
await asha.getByRole('button', { name: 'Add a step' }).click()
await asha.getByLabel('Role', { exact: true }).click()
await asha.getByRole('option', { name: 'reviewer' }).click()
await asha.getByLabel('department').check()
await asha.getByLabel('Allowed file types (blank = all)').fill('pdf, docx')
await asha.getByLabel('Keep for (days)').fill('730')
await asha.getByRole('button', { name: 'Add a field' }).click()
await asha.getByLabel('Key').fill('letter_ref')
await asha.getByLabel('Label', { exact: true }).fill('Letter reference')
await asha.getByRole('button', { name: 'Create category' }).click()
check('a category with a review step, rules and a field is created', await waitText(asha, 'HR Letters'))
await asha.getByRole('row', { name: /HR Letters/ }).getByRole('button', { name: 'Rules' }).click()
check('its rules come back when reopened', (await asha.getByLabel('Keep for (days)').inputValue()) === '730' && (await asha.getByLabel('Key').inputValue()) === 'letter_ref')
await asha.getByLabel('Keep for (days)').fill('365')
await asha.getByRole('button', { name: 'Publish new version' }).click()
await asha.getByRole('row', { name: /HR Letters/ }).getByText('v2').waitFor().catch(() => {})
check('changing the rules publishes a new version', (await asha.getByRole('row', { name: /HR Letters/ }).innerText()).includes('v2'))
await asha.getByRole('row', { name: /HR Letters/ }).getByRole('button', { name: 'Rename or move' }).click()
await asha.getByRole('textbox', { name: /^Name/ }).fill('HR Letters and Notices')
await asha.getByRole('button', { name: 'Save', exact: true }).click()
check('a category can be renamed', await waitText(asha, 'HR Letters and Notices'))

// Tags
await asha.getByRole('tab', { name: 'Tags' }).click()
await asha.getByLabel('New standard tag').fill('Urgent')
await asha.getByRole('button', { name: 'Add tag' }).click()
check('a standard tag is added', await waitText(asha, 'Urgent'))
await asha.getByRole('row', { name: /Urgent/ }).getByRole('button', { name: 'Turn off' }).click()
check('and switched off', await asha.getByRole('row', { name: /Urgent/ }).getByText('Inactive').waitFor().then(() => true).catch(() => false))
check('built-in tags cannot be changed', (await asha.getByRole('row', { name: /Pending/ }).getByText('Built in').count()) > 0)

// Organization editing
await asha.getByRole('link', { name: 'Organization' }).click()
await asha.getByRole('button', { name: 'Add' }).click()
await asha.getByRole('textbox', { name: /^Name/ }).fill('Legal')
await asha.getByLabel('Short code').fill('LEG')
await pick(asha, 'Manager', 'Rohan Deshmukh')
await asha.getByRole('button', { name: 'Save', exact: true }).click()
check('a department is added with its manager', (await waitText(asha, 'Legal')) && (await asha.getByRole('row', { name: /Legal/ }).innerText()).includes('Rohan Deshmukh'))
await asha.getByRole('row', { name: /Legal/ }).getByRole('button', { name: 'Edit' }).click()
await asha.getByRole('textbox', { name: /^Name/ }).fill('Legal and Compliance')
await asha.getByRole('button', { name: 'Save', exact: true }).click()
check('and renamed', await waitText(asha, 'Legal and Compliance'))
await asha.getByRole('tab', { name: 'Projects' }).click()
await asha.getByRole('row', { name: /Apollo/ }).getByRole('button', { name: 'People' }).click()
await pick(asha, 'Add a person', 'Neha Shah')
await asha.getByRole('button', { name: 'Add', exact: true }).click()
check('a person is added to a project', await waitText(asha, 'Neha Shah ·'))
await asha.getByRole('button', { name: 'End today' }).last().click()
check('and the membership can be ended (it stays visible until the end of the day)', await waitText(asha, ' · ends '))
await asha.getByRole('dialog').getByRole('button', { name: 'Close' }).click()
await asha.getByRole('tab', { name: 'Employees' }).click()
await asha.getByRole('row', { name: /Neha Shah/ }).getByRole('button', { name: 'Edit' }).click()
await pick(asha, 'Department', 'Legal and Compliance')
await asha.getByRole('button', { name: 'Save', exact: true }).click()
check('an employee is moved to the new department', (await waitText(asha, 'Legal and Compliance')) && (await asha.getByRole('row', { name: /Neha Shah/ }).innerText()).includes('Legal and Compliance'))

check('no script errors', errors.length === 0, errors.slice(0, 3).join(' | '))
await browser.close()
console.log(failed ? `${failed} check(s) FAILED` : 'ALL CHECKS PASSED')
process.exit(failed ? 1 : 0)
