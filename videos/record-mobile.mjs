/**
 * Video 08: the DMS on a phone (Sprint M1, phase 1): the phone layout, finding and opening documents,
 * uploading a photo, approving from the queue, and installing it on the home screen.
 * Recorded at phone size (390 x 844, touch) through the shared pipeline in lib.mjs. It changes data, so run it
 * on a fresh RECORDING database, not on the demo you browse. Environment: DMS_WEB_URL, DEMO_ACCESS_FILE.
 */
import path from 'node:path'
import { click, here, loadPassword, origin, recordVideo, redactor } from './lib.mjs'

const NAME = '08-dms-on-your-phone'
const password = loadPassword()
const asha = 'asha.kulkarni@demo.dms.test'
const photo = path.join(here, 'assets', 'delivery-receipt-photo.jpg')
const bar = (page) => page.getByRole('navigation', { name: 'Main' })

async function assertNoSecret(page) {
  if ((await page.locator('body').innerText()).includes(password)) throw new Error('The demo password is visible on screen')
}

const scenes = [
  {
    chapter: 'Chapter 1 — Introduction',
    title: 'The D M S on a phone',
    narration:
      'This video shows the D M S on a phone. It is the same application and the same address as on a computer. On a small screen it rearranges itself for one thumb: a bottom bar for the places used most, and pages that fit the width. This is the first phase. It covers signing in, the dashboard, finding documents, uploading, and approvals. It uses a recording copy of the demo organization.',
    actions: 'Open the sign-in page on a phone-sized screen.',
    expected: 'The sign-in form fits the phone.',
    run: async (page) => {
      await page.goto(origin + '/', { waitUntil: 'domcontentloaded' })
      await page.getByRole('button', { name: 'Sign in' }).waitFor()
    },
  },
  {
    chapter: 'Chapter 2 — Dashboard',
    title: 'Sign in and the dashboard',
    narration:
      'Asha signs in and lands on the dashboard. The four figures sit two to a row, and the charts and lists follow in a single column. The bottom bar always shows Dashboard, Documents, Upload and Approvals, with a red badge when reviews are waiting for her. Everything else is under More.',
    actions: 'Sign in and scroll the dashboard.',
    expected: 'Two figures per row and the bottom bar.',
    run: async (page) => {
      await page.getByLabel('Email').fill(asha)
      const field = page.getByLabel('Password')
      await field.fill(password)
      if ((await field.getAttribute('type')) !== 'password') throw new Error('The password field is not masked')
      await click(page.getByRole('button', { name: 'Sign in' }))
      await page.getByRole('heading', { name: 'Dashboard', exact: true }).waitFor()
      await page.getByText('Updated').waitFor()
      await page.waitForTimeout(2500)
      await page.mouse.wheel(0, 700)
      await page.waitForTimeout(2500)
      await page.mouse.wheel(0, -1400)
    },
  },
  {
    chapter: 'Chapter 3 — Finding documents',
    title: 'Search and filters',
    narration:
      'In Documents, each document is a compact card with its category, date, classification and status. Search sits at the top. The filters are folded away to save space, and open with one tap. Asha filters to internal documents, and only the internal ones remain.',
    actions: 'Open Documents, open the filters and filter by classification.',
    expected: 'The list narrows to internal documents.',
    run: async (page) => {
      await click(bar(page).getByRole('link', { name: 'Documents' }))
      await page.getByText('Mutual NDA Template').waitFor()
      await page.waitForTimeout(2000)
      await click(page.getByRole('button', { name: 'Filters' }))
      await click(page.getByLabel('Classification'))
      await click(page.getByRole('option', { name: /Internal/ }))
      await page.waitForTimeout(700)
      await click(page.getByRole('button', { name: 'Search', exact: true }))
      await page.getByText('Leave Policy 2026').waitFor()
      await page.waitForTimeout(2000)
    },
  },
  {
    chapter: 'Chapter 3 — Finding documents',
    title: 'Opening a document',
    narration:
      'Opening a document shows its details, then its versions, one card each, with Preview, Download and Restore as buttons. Preview shows a P D F or an image right on the screen, without leaving the application.',
    actions: 'Open a document and preview it.',
    expected: 'The document and its preview.',
    run: async (page) => {
      await click(page.getByRole('link', { name: 'Leave Policy 2026' }).first())
      await page.getByText('Versions').waitFor()
      await page.waitForTimeout(2000)
      await page.mouse.wheel(0, 500)
      await page.waitForTimeout(1800)
      await click(page.getByRole('button', { name: 'Preview' }).first())
      await page.getByRole('dialog').waitFor()
      await page.waitForTimeout(3000)
      await click(page.getByRole('button', { name: 'Close' }).last())
    },
  },
  {
    chapter: 'Chapter 4 — Capturing',
    title: 'Upload a photo',
    narration:
      'Upload has a Take a photo button. On a real phone it opens the camera, so a paper receipt can be photographed and filed on the spot. In this recording a saved photo of a delivery receipt stands in for the camera. She chooses a category, adds a title, picks a department, fills in the fields that category asks for, and uploads. The file is checked and stored, and she can open the new document straight away.',
    actions: 'Take a photo, choose a category and upload.',
    expected: 'The photo is uploaded.',
    run: async (page) => {
      await click(bar(page).getByRole('link', { name: 'Upload' }))
      await page.getByRole('heading', { name: 'Upload a document' }).waitFor()
      await click(page.getByLabel(/^Category/))
      await click(page.getByRole('option', { name: /Invoices/ }).first())
      await page.waitForTimeout(700)
      await page.locator('input[capture="environment"]').setInputFiles(photo)
      await page.getByText('delivery-receipt-photo.jpg').waitFor()
      await page.getByLabel(/^Title/).fill('Delivery receipt DR-20417')
      await click(page.getByLabel(/^Department/))
      await click(page.getByRole('option', { name: 'Finance' }))
      await page.getByLabel(/^Invoice number/).fill('DR-20417')
      await page.getByLabel('Vendor').fill('Northwind Logistics')
      await page.waitForTimeout(1200)
      await click(page.getByRole('button', { name: 'Upload', exact: true }))
      await page.getByText(/Uploaded and scanned/).waitFor()
      await page.waitForTimeout(2200)
    },
  },
  {
    chapter: 'Chapter 5 — Approvals',
    title: 'Approving from your phone',
    narration:
      'Reviews waiting for her appear as cards. She taps Review, and the review opens full screen. She can read the history, add a comment, and choose Approve or Reject. Approving from the phone takes seconds, and the red badge on the bottom bar clears.',
    actions: 'Open the queue, review and approve.',
    expected: 'The request is approved and the queue empties.',
    run: async (page) => {
      await click(bar(page).getByRole('link', { name: /Approvals/ }))
      await page.getByText('Vendor Agreement').waitFor()
      await page.waitForTimeout(1800)
      await click(page.getByRole('button', { name: 'Review' }).first())
      await page.getByRole('button', { name: 'Approve', exact: true }).waitFor()
      await page.waitForTimeout(1800)
      await page.getByLabel(/^Comment/).fill('Terms checked and agreed.')
      await page.waitForTimeout(1200)
      await click(page.getByRole('button', { name: 'Approve', exact: true }))
      await page.getByText('Nothing is waiting for your decision.').waitFor()
      await page.waitForTimeout(2000)
    },
  },
  {
    chapter: 'Chapter 6 — Everything else',
    title: 'More',
    narration:
      'Everything else is under More: shared documents, organization, people and the rest, each according to what the person is allowed to use. Sign out is here too. Those pages fit the screen, but they are designed for a computer, and will be refined in a later phase.',
    actions: 'Open More and one of its pages.',
    expected: 'The More list and a page from it.',
    run: async (page) => {
      await click(bar(page).getByRole('button', { name: 'More' }))
      await page.getByRole('link', { name: 'People' }).waitFor()
      await page.waitForTimeout(2800)
      await click(page.getByRole('link', { name: 'Shared', exact: true }))
      await page.getByRole('heading', { name: /Shared/ }).first().waitFor()
      await page.waitForTimeout(1500)
    },
  },
  {
    chapter: 'Chapter 7 — Installing',
    title: 'Put it on your home screen',
    narration:
      'There is nothing to download from an app store. On an Android phone, open the address in Chrome, open the menu and choose Install app. On an iPhone, open it in Safari, tap Share, then Add to Home Screen. A D M S icon, shown here, appears with your other apps, and the application opens full screen without the browser bar. Updates arrive by themselves when the application is updated on the server.',
    actions: 'Show the application icon.',
    expected: 'The icon is visible.',
    run: async (page) => {
      await page.goto(origin + '/icon-512.png', { waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(4500)
    },
  },
  {
    chapter: 'Chapter 8 — Summary',
    title: 'Summary',
    narration:
      'To summarize: the D M S now works on a phone from the same address. The dashboard, search, documents, camera upload and approvals have a phone layout, and everything else remains available. Offline use and push notifications are not part of this version.',
    actions: 'Return to the dashboard.',
    expected: 'The dashboard is visible.',
    run: async (page) => {
      await page.goto(origin + '/dashboard', { waitUntil: 'domcontentloaded' })
      await page.getByText('Updated').waitFor()
    },
  },
]

recordVideo({ name: NAME, scenes, password, check: assertNoSecret, mobile: true }).catch((error) => {
  console.error(redactor(password)(error))
  process.exit(1)
})
