/**
 * Video 02: choosing a design and the design catalogue (Sprints T0-T5).
 * Uses the shared pipeline in lib.mjs. Needs the demo API and web app running against the demo
 * database, the five designs published and the demo administrator made a platform administrator
 * (scripts/seed_demo.py does both). Publishing the sixth design changes demo data: use a fresh
 * demo database to record again.
 */
import path from 'node:path'
import { click, here, loadPassword, origin, recordVideo, redactor } from './lib.mjs'

const NAME = '02-dms-choose-your-design'
const password = loadPassword()
const sixth = path.join(here, 'assets', 'sixth-template-forest.json')
const invalid = path.join(here, 'assets', 'invalid-template.json')
const who = { sameer: 'sameer.patil@demo.dms.test', neha: 'neha.shah@demo.dms.test', asha: 'asha.kulkarni@demo.dms.test' }

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
const design = (page) => page.locator('[data-dms-template]').first().getAttribute('data-dms-template')
async function expectDesign(page, key) {
  await page.waitForFunction((k) => document.querySelector('[data-dms-template]')?.getAttribute('data-dms-template') === k, key, { timeout: 10000 })
}
async function assertNoSecret(page) {
  if ((await page.locator('body').innerText()).includes(password)) throw new Error('The demo password is visible on screen')
}
const appearance = async (page) => {
  await nav(page, 'Appearance')
  await page.getByRole('heading', { name: 'Choose your design' }).waitFor()
  await page.getByTestId('template-thumbnail').first().waitFor()
}

const scenes = [
  {
    chapter: 'Chapter 1 — Introduction',
    title: 'What is new',
    narration:
      'This video shows a new feature of the D M S web application: every person can choose how the application looks. A design changes colors, type, spacing, navigation and the style of tables, cards, buttons and tabs. It never changes the documents you can see or what you are allowed to do. The designs are stored as configuration, so a new design can be added without a software update.',
    actions: 'Open the sign-in page.',
    expected: 'The sign-in form is visible.',
    run: async (page) => {
      await page.goto(origin + '/', { waitUntil: 'domcontentloaded' })
      await page.getByRole('button', { name: 'Sign in' }).waitFor()
    },
  },
  {
    chapter: 'Chapter 2 — Choosing a design',
    title: 'Sameer opens Appearance',
    narration:
      'Sameer signs in. He has not chosen a design yet, so he sees the product default, Modern Enterprise, with a full sidebar and white workspace. The Appearance page in the menu lists every published design, each with a drawn preview, a name and a short description.',
    actions: 'Sign in as the employee and open Appearance.',
    expected: 'Five design cards with previews are shown; Modern Enterprise is marked as in use.',
    run: async (page) => {
      await signIn(page, who.sameer)
      await expectDesign(page, 'modern-enterprise')
      await appearance(page)
    },
  },
  {
    chapter: 'Chapter 2 — Choosing a design',
    title: 'Preview before applying',
    narration:
      'Preview shows a design on the real application without saving anything. Sameer previews Premium Dark. The whole application turns dark, with its own sidebar, type and card style. A bar at the bottom lets him apply the design or stop previewing. He moves to the document list while previewing, so he can judge it on real content.',
    actions: 'Preview Premium Dark, then open Documents.',
    expected: 'The application is dark; the preview bar is visible.',
    run: async (page) => {
      await click(page.getByTestId('design-premium-dark').getByRole('button', { name: 'Preview' }))
      await expectDesign(page, 'premium-dark')
      await page.getByText('Nothing is saved until you apply it.').waitFor()
      await page.waitForTimeout(1500)
      await nav(page, 'Documents')
      await page.getByRole('heading', { name: 'Documents', exact: true }).waitFor()
    },
  },
  {
    chapter: 'Chapter 2 — Choosing a design',
    title: 'Apply',
    narration:
      'He likes it and chooses Apply this design. The choice is saved to his account, in the database, so it follows him to any browser or device. From now on every page uses it, such as the document details with tabs.',
    actions: 'Apply the previewed design and open a document.',
    expected: 'The design stays dark after applying and while moving between pages.',
    run: async (page) => {
      await click(page.getByRole('button', { name: 'Apply this design' }))
      await page.getByText('Nothing is saved until you apply it.').waitFor({ state: 'detached' })
      await expectDesign(page, 'premium-dark')
      await page.getByRole('link', { name: /Invoice INV-1001/ }).first().click()
      await page.getByTestId('doc-title').waitFor()
    },
  },
  {
    chapter: 'Chapter 3 — Each person has their own',
    title: 'A colleague sees something different',
    narration:
      'Sameer signs out and his colleague Neha signs in. She is in the same organization, but sees the default design, not his. Her choice is hers alone. She picks Modern SaaS, which uses a floating sidebar, gradient cards and a card grid for the document list.',
    actions: 'Sign out, sign in as the colleague, choose Modern SaaS and open Documents.',
    expected: 'The colleague starts on the default design and ends on Modern SaaS.',
    run: async (page) => {
      await signOut(page)
      await signIn(page, who.neha)
      await expectDesign(page, 'modern-enterprise')
      await appearance(page)
      await click(page.getByTestId('design-modern-saas').getByRole('button', { name: 'Select' }))
      await expectDesign(page, 'modern-saas')
      await nav(page, 'Documents')
      await page.getByRole('heading', { name: 'Documents', exact: true }).waitFor()
    },
  },
  {
    chapter: 'Chapter 3 — Each person has their own',
    title: 'The choice follows the person',
    narration:
      'When Sameer signs in again, as he would on a different computer, the application opens in Premium Dark at once. His choice is stored on the server, not in the browser.',
    actions: 'Sign out and sign in again as the employee.',
    expected: 'The employee sees Premium Dark right after signing in.',
    run: async (page) => {
      await signOut(page)
      await signIn(page, who.sameer)
      await expectDesign(page, 'premium-dark')
    },
  },
  {
    chapter: 'Chapter 4 — Adding a design',
    title: 'The design catalogue',
    narration:
      'New designs are added by a platform administrator, a small group that is managed outside the web application. Asha is one. She has an extra screen, the Design catalogue, which lists every design, its version and whether it is a draft, published or archived.',
    actions: 'Sign in as the platform administrator and open the Design catalogue.',
    expected: 'The catalogue lists the designs with their status.',
    run: async (page) => {
      await signOut(page)
      await signIn(page, who.asha)
      await nav(page, 'Design catalogue')
      await page.getByRole('heading', { name: 'Design catalogue' }).waitFor()
      await page.getByRole('row', { name: /Premium Dark/ }).waitFor()
    },
  },
  {
    chapter: 'Chapter 4 — Adding a design',
    title: 'Unsafe files are refused',
    narration:
      'A design is a plain data file. Before anything is saved it is checked against a strict list of allowed values. Here the file hides a web address inside a color and markup inside the name. It is rejected with the reasons, and the save buttons stay disabled.',
    actions: 'Choose the invalid design file.',
    expected: 'The error list appears and saving is disabled.',
    run: async (page) => {
      await page.getByLabel('Design file').setInputFiles(invalid)
      await page.getByText('This file cannot be used.').waitFor()
    },
  },
  {
    chapter: 'Chapter 4 — Adding a design',
    title: 'Import and publish a new design',
    narration:
      'Now a sixth design, Forest Calm, a green theme with a compact toolbar. The check shows its name, description and version. Asha saves and publishes it. It is live straight away. No software update, rebuild or restart is needed.',
    actions: 'Choose the valid design file and save and publish it.',
    expected: 'Forest Calm appears in the list as Published.',
    run: async (page) => {
      await page.getByLabel('Design file').setInputFiles(sixth)
      await page.getByText('version 1.0.0').waitFor()
      await page.waitForTimeout(1200)
      await click(page.getByRole('button', { name: 'Save and publish' }))
      await page.getByRole('row', { name: /Forest Calm/ }).getByText('Published').waitFor()
    },
  },
  {
    chapter: 'Chapter 5 — Using the new design',
    title: 'Everyone can choose it',
    narration:
      'Back as Sameer, the Appearance page now offers six designs. He selects Forest Calm and the application restyles immediately: a calm green theme, a toolbar header, softer buttons and a list view of documents.',
    actions: 'Sign in as the employee, choose Forest Calm and open Documents.',
    expected: 'Forest Calm is applied.',
    run: async (page) => {
      await signOut(page)
      await signIn(page, who.sameer)
      await appearance(page)
      await page.getByTestId('design-forest-calm').waitFor()
      await click(page.getByTestId('design-forest-calm').getByRole('button', { name: 'Select' }))
      await expectDesign(page, 'forest-calm')
      await nav(page, 'Documents')
      await page.getByRole('heading', { name: 'Documents', exact: true }).waitFor()
    },
  },
  {
    chapter: 'Chapter 5 — Using the new design',
    title: 'Reset and summary',
    narration:
      'Reset to default removes his personal choice, and he is back on the default design. To summarize: five launch designs and a sixth added live, preview before applying, a separate choice for every person, saved on the server, and safe checking of every new design. The dashboard and report screens will use the same designs once they are built.',
    actions: 'Open Appearance and reset to the default.',
    expected: 'The default design is restored.',
    run: async (page) => {
      await appearance(page)
      await click(page.getByRole('button', { name: 'Reset to default' }))
      await expectDesign(page, 'modern-enterprise')
    },
  },
]

recordVideo({ name: NAME, scenes, password, check: assertNoSecret }).catch((error) => {
  console.error(redactor(password)(error))
  process.exit(1)
})
