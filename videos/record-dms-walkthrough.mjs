/**
 * DMS web application walkthrough (Sprint W1).
 * Reuses the CRM series pipeline from AadiProduct/dev-environment/videos/recordings/record-05-crm-rbac.mjs:
 * Playwright viewport capture at 1600x900, Microsoft Zira Desktop narration, FFmpeg H.264/AAC, SRT and VTT.
 * Also writes a narration CSV that uses the ScriptToVideo slides.csv column order.
 *
 * Needs the demo API (8000) and web app (5173) running against the demo database, and the
 * git-ignored docs/demo/DMS_DEMO_ACCESS.md. The password is read only to type it into masked fields.
 * Uploading and approving change demo data: re-seed a fresh demo database before recording again.
 */
import fs from 'node:fs'
import path from 'node:path'
import { click, here, loadPassword, origin, recordVideo, redactor, repo } from './lib.mjs'

const NAME = '01-dms-web-application-walkthrough'
const upload = path.join(here, 'assets', 'Service Agreement - Globex Logistics.pdf')
const password = loadPassword()
const who = {
  employee: 'sameer.patil@demo.dms.test',
  reviewer: 'meera.joshi@demo.dms.test',
  admin: 'asha.kulkarni@demo.dms.test',
  manager: 'rohan.deshmukh@demo.dms.test',
  project: 'priya.nair@demo.dms.test',
}

async function signIn(page, email) {
  await page.goto(origin + '/', { waitUntil: 'domcontentloaded' })
  await page.getByLabel('Email').fill(email)
  const field = page.getByLabel('Password')
  await field.fill(password)
  if ((await field.getAttribute('type')) !== 'password') throw new Error('The password field is not masked')
  await click(page.getByRole('button', { name: 'Sign in' }))
  await page.getByRole('heading', { name: /^(Dashboard|Documents)$/ }).waitFor()
  if (await page.getByRole('heading', { name: 'Dashboard', exact: true }).count()) { await page.getByRole('link', { name: 'Documents' }).first().click(); await page.getByRole('heading', { name: 'Documents', exact: true }).waitFor() }
}

async function signOut(page) {
  await click(page.getByRole('button', { name: 'Sign out' }))
  await page.getByRole('button', { name: 'Sign in' }).waitFor()
}

const nav = (page, name) => click(page.getByRole('link', { name }))

async function assertNoSecret(page) {
  const text = await page.locator('body').innerText()
  if (text.includes(password)) throw new Error('The demo password is visible on screen')
}

const scenes = [
  {
    chapter: 'Chapter 1 — Introduction',
    title: 'Sign-in page',
    narration:
      'This is the new D M S web application. It is a multi tenant document management system for small and medium organizations. Every person belongs to one organization, and sees only what their role and each document allow. This walkthrough uses a fictional organization called Demo Industries, with sample documents. You will sign in as an employee, a reviewer, an administrator, a department manager and a project manager.',
    actions: 'Open the sign-in page.',
    expected: 'The DMS sign-in form is visible.',
    run: async (page) => {
      await page.goto(origin + '/', { waitUntil: 'domcontentloaded' })
      await page.getByRole('button', { name: 'Sign in' }).waitFor()
    },
  },
  {
    chapter: 'Chapter 2 — Employee',
    title: 'Employee signs in and sees the document library',
    narration:
      'Sameer is an employee in the Finance department. He signs in with his work email and password. The password is typed into a masked field. After sign in, the document library opens. It lists only the documents Sameer is allowed to see, with the category, classification, status, version and size of each.',
    actions: 'Sign in as the employee.',
    expected: 'The Documents page lists documents with classification and status chips.',
    run: async (page) => {
      await signIn(page, who.employee)
      await page.getByText('Leave Policy 2026').first().waitFor()
    },
  },
  {
    chapter: 'Chapter 2 — Employee',
    title: 'Search and filters',
    narration:
      'Search looks through titles, file names, metadata and the text inside documents. Searching for acme finds the invoice and the vendor agreement. The classification filter narrows results further, and counts are calculated only over documents Sameer may see, so nothing leaks through the numbers.',
    actions: 'Search for acme, then filter by classification.',
    expected: 'Acme documents are listed; the filter keeps confidential documents only.',
    run: async (page) => {
      await page.getByLabel('Search documents in this page').fill('acme')
      await click(page.getByRole('button', { name: 'Search', exact: true }))
      await page.getByText('Invoice INV-1001 Acme Supplies').first().waitFor()
      await page.waitForTimeout(1200)
      await click(page.getByLabel('Classification'))
      await click(page.getByRole('option', { name: /^Confidential/ }))
      await page.getByText('Invoice INV-1001 Acme Supplies').first().waitFor()
    },
  },
  {
    chapter: 'Chapter 2 — Employee',
    title: 'Document details, metadata and versions',
    narration:
      'Opening a document shows its details. The invoice carries the metadata its category requires, such as the invoice number and vendor, the date until which it must be kept, and its version history. Preview and download are separate rights. Each issues a short lived secure link, and every download is recorded in the audit log.',
    actions: 'Open the invoice detail page.',
    expected: 'Details, metadata, versions with Preview and Download buttons, and the retention date are shown.',
    run: async (page) => {
      await click(page.getByRole('link', { name: 'Invoice INV-1001 Acme Supplies' }))
      await page.getByTestId('doc-title').waitFor()
      await page.getByText('Keep until').waitFor()
      await page.getByRole('button', { name: 'Download' }).first().waitFor()
    },
  },
  {
    chapter: 'Chapter 2 — Employee',
    title: 'Upload a document that needs approval',
    narration:
      'Now Sameer uploads a contract. He chooses the Contracts category, picks the file, and the form asks for what that category requires: a department and a contract reference. The category is configured so that documents are reviewed before release, and the form says so. The file is checked for its real type and scanned before it is stored.',
    actions: 'Open Upload, choose the Contracts category, select a file, fill the required fields and upload.',
    expected: 'A success message says the document is waiting for approval.',
    run: async (page) => {
      await nav(page, 'Upload')
      await page.getByRole('heading', { name: 'Upload a document' }).waitFor()
      await click(page.getByLabel('Category'))
      await click(page.getByRole('option', { name: 'Contracts' }))
      await page.getByText('reviewed before they are released').waitFor()
      await page.getByLabel('File', { exact: true }).setInputFiles(upload)
      await page.getByLabel('Title (defaults to the file name)').fill('Service Agreement - Globex Logistics')
      await click(page.getByLabel('Department'))
      await click(page.getByRole('option', { name: 'Finance' }))
      await page.getByLabel(/Contract reference/).fill('CT-0031')
      await click(page.getByRole('button', { name: 'Upload', exact: true }))
      await page.getByText('waiting for approval').waitFor()
    },
  },
  {
    chapter: 'Chapter 3 — Reviewer',
    title: 'Reviewer approves',
    narration:
      'Meera is a reviewer. After she signs in, the menu shows how many approvals are waiting for her. She opens the new service agreement, reads the history, and approves it with a comment. A rejection would require a reason. Nobody can approve their own upload, and every decision is recorded.',
    actions: 'Sign out, sign in as the reviewer, open Approvals and approve the new agreement.',
    expected: 'The review dialog opens and the item leaves the queue after approval.',
    run: async (page) => {
      await signOut(page)
      await signIn(page, who.reviewer)
      await nav(page, 'Approvals')
      await page.getByRole('heading', { name: 'Approvals waiting for you' }).waitFor()
      const row = page.getByRole('row', { name: /Service Agreement - Globex Logistics/ })
      await click(row.getByRole('button', { name: 'Review' }))
      await page.getByLabel('Comment (required to reject)').fill('Terms match the approved template.')
      await page.waitForTimeout(1000)
      await click(page.getByRole('button', { name: 'Approve', exact: true }))
      await page.getByRole('row', { name: /Service Agreement - Globex Logistics/ }).waitFor({ state: 'detached' })
    },
  },
  {
    chapter: 'Chapter 4 — Administrator',
    title: 'Administrator sees every document',
    narration:
      'Asha is the organization administrator. Her library includes documents others cannot see, such as the highly confidential salary letters, and archived documents. Administrator access to restricted documents is an audited privilege, so every use leaves a record. Filtering by status shows the archived remote work guidelines.',
    actions: 'Sign in as the administrator and filter by Archived.',
    expected: 'The administrator sees the salary letters and the archived guidelines.',
    run: async (page) => {
      await signOut(page)
      await signIn(page, who.admin)
      await page.getByText('Salary Revision Letters FY26').first().waitFor()
      await page.waitForTimeout(1500)
      await click(page.getByLabel('Status'))
      await click(page.getByRole('option', { name: 'Archived' }))
      await page.getByText('Remote Work Guidelines 2023').first().waitFor()
    },
  },
  {
    chapter: 'Chapter 4 — Administrator',
    title: 'Document lifecycle',
    narration:
      'Documents have a lifecycle. An approved document can be archived, which keeps it readable but closed to new versions and edits, and an archived document can be restored. Categories also define how long a document must be kept and when it should be reviewed. Legal holds and approved deletion already work in the system programming interface, and will get screens in a later release.',
    actions: 'Open the archived document.',
    expected: 'The Restore from archive button is shown.',
    run: async (page) => {
      await click(page.getByRole('link', { name: 'Remote Work Guidelines 2023' }))
      await page.getByRole('button', { name: 'Restore from archive' }).waitFor()
    },
  },
  {
    chapter: 'Chapter 4 — Administrator',
    title: 'Organization structure',
    narration:
      'The organization page shows the departments, branches, projects and designations that documents are filed against, and the employee directory. Access rules use this structure. For example, confidential finance documents are visible to the Finance department and to its manager.',
    actions: 'Open Organization and browse the tabs.',
    expected: 'Departments, projects and employees are listed.',
    run: async (page) => {
      await nav(page, 'Organization')
      await page.getByText('Finance').first().waitFor()
      await page.waitForTimeout(1500)
      await click(page.getByRole('tab', { name: 'Projects' }))
      await page.getByText('Apollo ERP Rollout').waitFor()
      await page.waitForTimeout(1200)
      await click(page.getByRole('tab', { name: 'Employees' }))
      await page.getByText('Priya Nair').waitFor()
    },
  },
  {
    chapter: 'Chapter 4 — Administrator',
    title: 'Roles and permissions',
    narration:
      'The account page lists exactly what the signed in person is allowed to do. Roles grant actions, such as upload, approve or archive. Whether a person can open one particular document is decided separately, from its classification, its owner, its department and project, and any direct sharing.',
    actions: 'Open Account.',
    expected: 'The permission groups are displayed.',
    run: async (page) => {
      await nav(page, 'Account')
      await page.getByText('What your roles allow').waitFor()
    },
  },
  {
    chapter: 'Chapter 5 — Managers',
    title: 'Department manager',
    narration:
      'Rohan manages the Finance department. He sees the confidential finance documents for his department, including invoices and contracts, because the access policy gives department managers visibility into their own department. He does not see the salary letters, which belong to Human Resources.',
    actions: 'Sign in as the department manager.',
    expected: 'Finance documents are listed, the salary letters are not.',
    run: async (page) => {
      await signOut(page)
      await signIn(page, who.manager)
      await page.getByText('Invoice INV-1002 Northwind Logistics').first().waitFor()
      await page.waitForTimeout(1500)
      if ((await page.getByText('Salary Revision Letters FY26').count()) > 0) throw new Error('Manager can see HR records')
    },
  },
  {
    chapter: 'Chapter 5 — Managers',
    title: 'Project manager and sharing',
    narration:
      'Priya manages the Apollo project. An employee shared the Acme invoice with her directly, with permission to view and download. The shared page lists what has been shared with you and what you have shared with others. Sharing can expire, can be withdrawn at any time, and never gives more than the person role already allows.',
    actions: 'Sign in as the project manager and open Shared.',
    expected: 'The shared invoice is listed with view and download access.',
    run: async (page) => {
      await signOut(page)
      await signIn(page, who.project)
      await nav(page, 'Shared')
      await page.getByRole('cell', { name: 'Invoice INV-1001 Acme Supplies' }).waitFor()
      await page.getByText('View and download').waitFor()
    },
  },
  {
    chapter: 'Chapter 6 — Summary',
    title: 'What is available and what comes next',
    narration:
      'This first release of the web application covers sign in, the document library with search and filters, document details with versions and retention, upload with validation, approvals, sharing lists, lifecycle archiving, the organization directory, and role based permissions. Still to come are the screens for sharing and uploading new versions, administration of users and categories, reports and dashboards, and notifications. Thank you for watching.',
    actions: 'Return to the library.',
    expected: 'The Documents page is visible.',
    run: async (page) => {
      await nav(page, 'Documents')
      await page.getByRole('heading', { name: 'Documents', exact: true }).waitFor()
    },
  },
]

recordVideo({ name: NAME, scenes, password, check: assertNoSecret }).catch((error) => {
  console.error(redactor(password)(error))
  process.exit(1)
})
