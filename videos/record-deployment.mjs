/**
 * Video 07: deployment readiness (Sprint C1): the stack that Coolify will run, shown through its one public
 * address on a local copy. Uses the shared pipeline in lib.mjs. It changes data, so run it against a FRESH stack
 * (docker compose -p dmsstack ... down -v, then up) whose first organization was created with
 * `python -m app.provision create-org ...`. Environment: DMS_WEB_URL (the stack's address, for example
 * http://localhost:8088) and DMS_FIRST_LINK (the one-time link that command printed).
 */
import path from 'node:path'
import { click, here, origin, recordVideo, redactor } from './lib.mjs'

const NAME = '07-dms-deployment'
const firstLink = process.env.DMS_FIRST_LINK
if (!firstLink) throw new Error('Set DMS_FIRST_LINK to the one-time link from `python -m app.provision create-org`')
const email = process.env.DMS_FIRST_EMAIL ?? 'owner@stacktest.example'
const password = 'Stack-Video-Passphrase-2026'
const pdf = path.join(here, 'assets', 'Service Agreement - Globex Logistics.pdf')
const nav = (page, name) => click(page.getByRole('link', { name }).first())

async function assertNoSecret(page) {
  if ((await page.locator('body').innerText()).includes(password)) throw new Error('The password is visible on screen')
}

const scenes = [
  {
    chapter: 'Chapter 1 — Introduction',
    title: 'What is being deployed',
    narration:
      'This video shows the D M S as it will run on a server. Three programs start together: the web application, the D M S service behind it, and the database. Visitors only ever see one web address. Everything here runs on a local copy of the same setup that Coolify will use, because no server has been prepared yet. It has not been deployed to a real server.',
    actions: 'Open the application address.',
    expected: 'The sign-in page is visible.',
    run: async (page) => {
      await page.goto(origin + '/', { waitUntil: 'domcontentloaded' })
      await page.getByRole('button', { name: 'Sign in' }).waitFor()
    },
  },
  {
    chapter: 'Chapter 2 — Health',
    title: 'Is it running?',
    narration:
      'Two addresses report health. The first answers from the web container. The second goes through the web container to the D M S service, and answers with a status of ok. If either stops answering, Coolify can see it and restart the container. The service itself cannot be reached except through the web address.',
    actions: 'Open the two health addresses.',
    expected: 'Both answer ok.',
    run: async (page) => {
      await page.goto(origin + '/healthz', { waitUntil: 'domcontentloaded' })
      await page.getByText('ok').first().waitFor()
      await page.waitForTimeout(2500)
      await page.goto(origin + '/api/v1/health', { waitUntil: 'domcontentloaded' })
      await page.getByText('"status"').waitFor()
    },
  },
  {
    chapter: 'Chapter 3 — First administrator',
    title: 'The first organization and administrator',
    narration:
      'A brand new installation has no users. There is deliberately no public screen to create an organization. Instead, the person running the server uses one command, which creates the organization and its first administrator and prints a single use link. This link was created beforehand. Opening it, the administrator chooses a password, then signs in. The link stops working as soon as it has been used.',
    actions: 'Open the one-time link, choose a password, sign in.',
    expected: 'The administrator reaches the dashboard.',
    run: async (page) => {
      await page.goto(firstLink, { waitUntil: 'domcontentloaded' })
      await page.getByLabel('New password', { exact: true }).fill(password)
      await page.getByLabel('Repeat password').fill(password)
      await page.waitForTimeout(900)
      await click(page.getByRole('button', { name: 'Save password' }))
      await page.getByText('Your password was changed').waitFor()
      await page.getByLabel('Email').fill(email)
      await page.getByLabel('Password').fill(password)
      await click(page.getByRole('button', { name: 'Sign in' }))
      await page.getByRole('heading', { name: 'Dashboard', exact: true }).waitFor()
      await page.getByText('Updated').waitFor()
      await page.waitForTimeout(1500)
    },
  },
  {
    chapter: 'Chapter 4 — Ready to use',
    title: 'Designs are already published',
    narration:
      'The five standard designs are published automatically every time the service starts, so nothing needs to be imported by hand. The Appearance page lists them, and each person can choose their own.',
    actions: 'Open Appearance.',
    expected: 'Five designs are listed.',
    run: async (page) => {
      await nav(page, 'Appearance')
      await page.getByTestId('design-premium-dark').waitFor()
      await page.waitForTimeout(2500)
    },
  },
  {
    chapter: 'Chapter 4 — Ready to use',
    title: 'Storing a first document',
    narration:
      'The administrator creates a first category, then uploads a document. The file goes through the web address to the service, is checked, stored, and appears in the library. In this local copy the files are kept on a disk volume. On a server they go to the Backblaze bucket. Virus scanning is switched off for this first release, and the record of each file says that it was not scanned. It can be turned on later without changing the application.',
    actions: 'Create a category, upload a document, open it.',
    expected: 'The document is listed and opens.',
    run: async (page) => {
      await nav(page, 'Categories')
      await click(page.getByRole('button', { name: 'New category' }))
      await page.getByRole('textbox', { name: /^Name/ }).fill('General')
      await page.waitForTimeout(700)
      await click(page.getByRole('button', { name: 'Create category' }))
      await page.getByText('General').first().waitFor()
      await nav(page, 'Upload')
      await click(page.getByLabel(/^Category/))
      await click(page.getByRole('option', { name: /General/ }))
      await page.getByLabel('File', { exact: true }).setInputFiles(pdf)
      await page.waitForTimeout(900)
      await click(page.getByRole('button', { name: 'Upload', exact: true }))
      await page.getByText('Service Agreement').first().waitFor()
      await page.waitForTimeout(1500)
      await nav(page, 'Documents')
      await page.getByRole('link', { name: /Service Agreement/ }).first().waitFor()
    },
  },
  {
    chapter: 'Chapter 5 — Bringing people in',
    title: 'Inviting colleagues before email is ready',
    narration:
      'Colleagues join by invitation from the People page. The invitation normally goes out by email. Email needs a sending service, and that is a setting, not part of the application. Until it is set, the person running the server can print a single use link for anyone with the link command and send it by any means. Once the email service is verified, only four values are entered and nothing else changes. Switching provider later is the same four values.',
    actions: 'Invite a colleague and show the pending invitation.',
    expected: 'The invitation is listed as waiting.',
    run: async (page) => {
      await nav(page, 'People')
      await click(page.getByRole('button', { name: 'Invite someone' }))
      await page.getByLabel('Work email').fill('colleague@stacktest.example')
      await page.getByLabel('Full name').fill('First Colleague')
      await page.waitForTimeout(900)
      await click(page.getByRole('button', { name: 'Send invitation' }))
      await click(page.getByRole('tab', { name: /Invitations/ }))
      await page.getByRole('row', { name: /First Colleague/ }).waitFor()
      await page.waitForTimeout(2500)
    },
  },
  {
    chapter: 'Chapter 6 — Summary',
    title: 'What is left',
    narration:
      'To summarize: the web application, service and database start together behind one address, the first administrator is created with one command, documents upload and open, and the standard designs are ready. What remains is on the server side: a Coolify server and domain, a verified email service, a production storage bucket, and then entering those settings. Virus scanning and sign in with Google or Microsoft can be switched on later.',
    actions: 'Return to the dashboard.',
    expected: 'The dashboard is visible.',
    run: async (page) => {
      await nav(page, 'Dashboard')
      await page.getByText('Updated').waitFor()
    },
  },
]

recordVideo({ name: NAME, scenes, password, check: assertNoSecret }).catch((error) => {
  console.error(redactor(password)(error))
  process.exit(1)
})
