/**
 * Video 03: working with documents (Sprint W2a): edit, new version, in-page preview, restore,
 * sharing, review comments and resubmission, legal hold, approved deletion and the due-soon list.
 * Uses the shared pipeline in lib.mjs. It changes data, and prepares two situations directly in
 * the database (a keep-until date that has passed, and one that is near), so run it on a fresh
 * RECORDING database, not on the demo you browse. Environment: DMS_WEB_URL, DEMO_ACCESS_FILE,
 * PGDATABASE (name of the recording database).
 */
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { click, here, loadPassword, origin, recordVideo, redactor } from './lib.mjs'

const NAME = '03-dms-working-with-documents'
const password = loadPassword()
const db = process.env.PGDATABASE ?? 'dms_demo_w2'
const sql = (q) => execFileSync('docker', ['exec', 'dms-postgres-1', 'psql', '-U', 'dms', '-d', db, '-q', '-c', q], { encoding: 'utf8' })
const pdf = path.join(here, 'assets', 'Service Agreement - Globex Logistics.pdf')
const who = {
  sameer: 'sameer.patil@demo.dms.test', priya: 'priya.nair@demo.dms.test', meera: 'meera.joshi@demo.dms.test', asha: 'asha.kulkarni@demo.dms.test',
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
const nav = (page, name) => click(page.getByRole('link', { name }).first())
async function openDoc(page, title) {
  await nav(page, 'Documents')
  await click(page.getByRole('link', { name: title }).first())
  await page.getByTestId('doc-title').waitFor()
}
async function assertNoSecret(page) {
  if ((await page.locator('body').innerText()).includes(password)) throw new Error('The demo password is visible on screen')
}
const dialog = (page) => page.getByRole('dialog')

const scenes = [
  {
    chapter: 'Chapter 1 — Introduction',
    title: 'What this video covers',
    narration:
      'This video shows what people can now do with a document in the D M S web application, without leaving the browser: edit its details, add and restore versions, preview it on the page, share it, discuss a review, place a legal hold, and delete it with a second person approval. It uses a recording copy of the demo organization with sample documents.',
    actions: 'Open the sign-in page.',
    expected: 'The sign-in form is visible.',
    run: async (page) => {
      await page.goto(origin + '/', { waitUntil: 'domcontentloaded' })
      await page.getByRole('button', { name: 'Sign in' }).waitFor()
    },
  },
  {
    chapter: 'Chapter 2 — Your own documents',
    title: 'Uploaded by me and editing details',
    narration:
      'Sameer is an employee. The toggle above the list narrows it to the documents he uploaded. He opens an invoice and chooses Edit details. He can correct the title and the extra fields its category asks for. Every save is checked against the version he started from, so he can never overwrite someone else’s change.',
    actions: 'Sign in as the employee, filter to Uploaded by me, open the invoice, edit title and vendor.',
    expected: 'The document page shows the new title and vendor.',
    run: async (page) => {
      await signIn(page, who.sameer)
      await click(page.getByRole('button', { name: 'Uploaded by me' }))
      await page.getByText('Invoice INV-1001').first().waitFor()
      await openDoc(page, 'Invoice INV-1002 Northwind Logistics')
      await click(page.getByRole('button', { name: 'Edit details' }))
      await page.getByLabel('Title').fill('Invoice INV-1002 Northwind Logistics (paid)')
      await page.getByLabel('Vendor').fill('Northwind Logistics Ltd')
      await page.waitForTimeout(900)
      await click(page.getByRole('button', { name: 'Save changes' }))
      await page.getByText('Northwind Logistics Ltd').first().waitFor()
    },
  },
  {
    chapter: 'Chapter 2 — Your own documents',
    title: 'Adding a version',
    narration:
      'A scanned copy of the paid invoice arrives. Sameer chooses New version, selects the file and says what changed. The file is checked and scanned, and becomes version two, the current one. Version one is kept. If a colleague had added a version in the meantime, the system would refuse and tell him, rather than silently replacing their work.',
    actions: 'Add a new version with a comment.',
    expected: 'Version 2 is current.',
    run: async (page) => {
      await click(page.getByRole('button', { name: 'New version' }))
      await page.getByLabel('New version file').setInputFiles(pdf)
      await page.getByLabel('What changed (optional)').fill('Scanned copy of the paid invoice')
      await page.waitForTimeout(900)
      await click(page.getByRole('button', { name: 'Upload version' }))
      await page.getByText('The new version was uploaded and scanned').waitFor()
      await page.waitForTimeout(1200)
      await click(dialog(page).getByRole('button', { name: 'Done' }))
      await page.getByRole('row', { name: /v2/ }).getByText('Current').waitFor()
    },
  },
  {
    chapter: 'Chapter 2 — Your own documents',
    title: 'Preview on the page and restoring a version',
    narration:
      'Preview now opens the file on the page for PDFs and images, using a short lived secure link. Other file types, such as the original Excel sheet, say that they have no preview and can be downloaded instead. If the old version turns out to be the right one, Restore makes a new version from it. Nothing is rewritten, so the history stays complete.',
    actions: 'Preview version 2, then restore version 1.',
    expected: 'A PDF preview opens; version 3 appears as the restored copy.',
    run: async (page) => {
      await click(page.getByRole('row', { name: /v2/ }).getByRole('button', { name: 'Preview' }))
      await page.locator('iframe[title="Document preview"]').waitFor()
      await page.waitForTimeout(2500)
      await click(dialog(page).getByRole('button', { name: 'Close' }))
      await click(page.getByRole('row', { name: /v1/ }).getByRole('button', { name: 'Restore' }))
      await page.getByText('was restored as a new version').waitFor()
      await page.getByRole('row', { name: /v3/ }).waitFor()
    },
  },
  {
    chapter: 'Chapter 3 — Sharing',
    title: 'Sharing with a colleague',
    narration:
      'Share opens a dialog. Sameer types part of a colleague’s name, chooses Priya, gives her view and download access, and shares. The list shows who has access, and Stop sharing removes it at any time, for every version at once. Sharing can never give someone more than their role allows.',
    actions: 'Share the invoice with a colleague.',
    expected: 'The colleague appears under Shared with.',
    run: async (page) => {
      await click(page.getByRole('button', { name: 'Share' }))
      await page.getByLabel('Colleague').fill('Priya')
      await click(page.getByRole('option', { name: /Priya Nair/ }))
      await click(page.getByLabel('Access'))
      await click(page.getByRole('option', { name: 'View and download' }))
      await page.waitForTimeout(800)
      await click(dialog(page).getByRole('button', { name: 'Share', exact: true }))
      await dialog(page).getByText('Priya Nair · view and download').waitFor()
      await page.waitForTimeout(1200)
      await click(dialog(page).getByRole('button', { name: 'Close' }))
    },
  },
  {
    chapter: 'Chapter 3 — Sharing',
    title: 'The colleague sees it',
    narration:
      'Priya signs in and finds the invoice on her Shared page, with the access she was given. It does not appear anywhere else in her library, because the invoice is confidential and belongs to another department.',
    actions: 'Sign in as the colleague and open Shared.',
    expected: 'The invoice is listed as shared with view and download access.',
    run: async (page) => {
      await signOut(page)
      await signIn(page, who.priya)
      await nav(page, 'Shared')
      await page.getByRole('cell', { name: /Invoice INV-1002/ }).waitFor()
    },
  },
  {
    chapter: 'Chapter 4 — Reviews',
    title: 'Commenting on a review',
    narration:
      'A contract that needs approval is waiting for review. Its submitter can add a comment for the reviewers on the document page, here a note that the signed copy is attached.',
    actions: 'Open the contract under review and comment.',
    expected: 'The comment appears in the approval history.',
    run: async (page) => {
      await signOut(page)
      await signIn(page, who.sameer)
      await openDoc(page, 'Vendor Agreement - Acme Supplies')
      await page.getByLabel('Review comment').fill('The signed copy is attached to the ticket.')
      await click(page.getByRole('button', { name: 'Comment', exact: true }))
      await page.getByText('The signed copy is attached to the ticket.').first().waitFor()
    },
  },
  {
    chapter: 'Chapter 4 — Reviews',
    title: 'Rejected, corrected and sent again',
    narration:
      'Meera, the reviewer, finds the signature page missing and rejects the contract. A reason is required. Sameer sees the decision and its reason on the document and, once he has fixed the problem, chooses Send for review again. The earlier rejection stays on record.',
    actions: 'Reviewer rejects with a reason; the submitter sends it for review again.',
    expected: 'The history shows the rejection and the new review.',
    run: async (page) => {
      await signOut(page)
      await signIn(page, who.meera)
      await nav(page, 'Approvals')
      await click(page.getByRole('row', { name: /Vendor Agreement - Acme Supplies/ }).getByRole('button', { name: 'Review' }))
      await page.getByLabel('Comment (required to reject)').fill('The signature page is missing.')
      await page.waitForTimeout(900)
      await click(page.getByRole('button', { name: 'Reject', exact: true }))
      await page.getByRole('row', { name: /Vendor Agreement - Acme Supplies/ }).waitFor({ state: 'detached' })
      await signOut(page)
      await signIn(page, who.sameer)
      await openDoc(page, 'Vendor Agreement - Acme Supplies')
      await page.getByText('The signature page is missing.').first().waitFor()
      await page.waitForTimeout(1500)
      await click(page.getByRole('button', { name: 'Send for review again' }))
      await page.getByText('Sent for review again').waitFor()
    },
  },
  {
    chapter: 'Chapter 5 — Retention and disposal',
    title: 'Legal hold blocks deletion',
    narration:
      'The paid invoice has passed its keep-until date, so it could be deleted. But Asha, the administrator, places a legal hold on it, with a reason that is recorded. While the hold is on, a deletion request is refused. Releasing the hold, again with a reason, makes deletion possible.',
    actions: 'Place a legal hold, try to request deletion, release the hold.',
    expected: 'The request is refused with the hold as the reason; the hold is then released.',
    run: async (page) => {
      sql('UPDATE documents SET retention_until = current_date - 1')
      await signOut(page)
      await signIn(page, who.asha)
      await openDoc(page, 'Invoice INV-1002 Northwind Logistics (paid)')
      await click(page.getByRole('button', { name: 'Place legal hold' }))
      await page.getByLabel('Reason').fill('Litigation 2026-14')
      await page.waitForTimeout(900)
      await click(page.getByRole('button', { name: 'Place hold' }))
      await page.getByText('Legal hold: Litigation 2026-14').waitFor()
      await click(page.getByRole('button', { name: 'Request deletion' }))
      await page.getByLabel('Reason').fill('Cleaning up paid invoices')
      await click(page.getByRole('button', { name: 'Send request' }))
      await page.getByText(/legal hold/i).first().waitFor()
      await page.waitForTimeout(1800)
      await click(dialog(page).getByRole('button', { name: 'Cancel' }))
      await click(page.getByRole('button', { name: 'Release legal hold' }))
      await page.getByLabel('Reason').fill('Case closed')
      await click(page.getByRole('button', { name: 'Release hold' }))
      await page.getByText('No legal hold.').waitFor()
    },
  },
  {
    chapter: 'Chapter 5 — Retention and disposal',
    title: 'Deletion needs a second person',
    narration:
      'Sameer, who owns the invoice, asks for it to be deleted and gives a reason. Nothing is removed yet. A different person with approval rights must decide. Asha opens the Retention page, sees the request, and after a clear warning that the files will be permanently removed, approves it. The invoice disappears from every list. Only a record that it existed remains.',
    actions: 'The owner requests deletion; the administrator approves it on the Retention page.',
    expected: 'The Retention page confirms the deletion.',
    run: async (page) => {
      await signOut(page)
      await signIn(page, who.sameer)
      await openDoc(page, 'Invoice INV-1002 Northwind Logistics (paid)')
      await click(page.getByRole('button', { name: 'Request deletion' }))
      await page.getByLabel('Reason').fill('Duplicate of INV-1001')
      await page.waitForTimeout(900)
      await click(page.getByRole('button', { name: 'Send request' }))
      await page.getByText('Deletion requested').waitFor()
      await page.waitForTimeout(1200)
      await signOut(page)
      await signIn(page, who.asha)
      await nav(page, 'Retention')
      await click(page.getByRole('tab', { name: /Deletion requests/ }))
      await click(page.getByRole('row', { name: /Invoice INV-1002/ }).getByRole('button', { name: 'Approve deletion' }))
      await page.waitForTimeout(1800)
      await click(page.getByRole('button', { name: 'Delete permanently' }))
      await page.getByText('Deleted. The stored files were removed').waitFor()
    },
  },
  {
    chapter: 'Chapter 5 — Retention and disposal',
    title: 'What is coming due',
    narration:
      'The Due soon tab lists documents whose keep-until date or review date is approaching or has passed, so nothing is kept or deleted by accident. Here the contract template reaches its date within two weeks. This list is what the later notification feature will send as reminders.',
    actions: 'Open the Due soon tab.',
    expected: 'Documents nearing their dates are listed.',
    run: async (page) => {
      sql("UPDATE documents SET retention_until = current_date + 12 WHERE title = 'Mutual NDA Template'")
      await page.reload()
      await click(page.getByRole('tab', { name: 'Due soon' }))
      await page.getByText('Mutual NDA Template').first().waitFor()
      await page.waitForTimeout(1500)
    },
  },
  {
    chapter: 'Chapter 6 — Summary',
    title: 'Summary',
    narration:
      'In short: edit with overwrite protection, add and restore versions, preview on the page, share and stop sharing, discuss and resubmit reviews, hold, and delete only with a reason, a second approver and no hold. Still to come in the web application are the administration screens for users, categories and the organization, and the account pages for invitations and two step verification.',
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
