/**
 * Video 06: the dashboard (Sprint 19): the first page after sign-in, what each figure and card means,
 * how the numbers follow what a person may see, and how each design arranges the same information.
 * Uses the shared pipeline in lib.mjs. It changes data (design choices), so run it on a fresh RECORDING
 * database, not on the demo you browse. Environment: DMS_WEB_URL, DEMO_ACCESS_FILE.
 */
import { click, loadPassword, origin, recordVideo, redactor } from './lib.mjs'

const NAME = '06-dms-dashboard'
const password = loadPassword()
const asha = 'asha.kulkarni@demo.dms.test'
const sameer = 'sameer.patil@demo.dms.test'

async function signIn(page, email) {
  await page.goto(origin + '/', { waitUntil: 'domcontentloaded' })
  await page.getByLabel('Email').fill(email)
  const field = page.getByLabel('Password')
  await field.fill(password)
  if ((await field.getAttribute('type')) !== 'password') throw new Error('The password field is not masked')
  await click(page.getByRole('button', { name: 'Sign in' }))
  await page.getByRole('heading', { name: 'Dashboard', exact: true }).waitFor()
}
const signOut = async (page) => {
  await click(page.getByRole('button', { name: 'Sign out' }))
  await page.getByRole('button', { name: 'Sign in' }).waitFor()
}
const nav = (page, name) => click(page.getByRole('link', { name }).first())
async function applyDesign(page, key) {
  await nav(page, 'Appearance')
  await click(page.getByTestId(`design-${key}`).getByRole('button', { name: 'Preview' }))
  await click(page.getByRole('button', { name: 'Apply this design' }))
  await page.waitForTimeout(1200)
  await nav(page, 'Dashboard')
  await page.getByRole('heading', { name: 'Dashboard', exact: true }).waitFor()
  await page.getByText('Updated').waitFor()
}
async function assertNoSecret(page) {
  if ((await page.locator('body').innerText()).includes(password)) throw new Error('The demo password is visible on screen')
}

const scenes = [
  {
    chapter: 'Chapter 1 — Introduction',
    title: 'What this video covers',
    narration:
      'This video shows the new dashboard of the D M S web application. It is the first page people see after signing in, and it answers a simple question: what needs my attention, and what is happening with my documents? It uses a recording copy of the demo organization.',
    actions: 'Open the sign-in page.',
    expected: 'The sign-in form is visible.',
    run: async (page) => {
      await page.goto(origin + '/', { waitUntil: 'domcontentloaded' })
      await page.getByRole('button', { name: 'Sign in' }).waitFor()
    },
  },
  {
    chapter: 'Chapter 2 — The dashboard',
    title: 'The first page after sign-in',
    narration:
      'Asha, the organization administrator, signs in and lands on the dashboard. Four figures sit at the top: how many documents she can see, how many reviews are waiting for her, how many documents were shared with her, and how much storage those documents use. Each figure that leads somewhere is a link.',
    actions: 'Sign in and show the four figures.',
    expected: 'The dashboard opens with four figures.',
    run: async (page) => {
      await signIn(page, asha)
      await page.getByText('Updated').waitFor()
      await page.waitForTimeout(1500)
    },
  },
  {
    chapter: 'Chapter 2 — The dashboard',
    title: 'Charts and lists',
    narration:
      'Below the figures are two charts and two lists. The first chart shows how many documents were added each day over the last thirty days. The second shows the documents by classification. The lists show the most recent documents, and the reviews waiting in her queue. Every title opens that document.',
    actions: 'Scroll through the charts and lists.',
    expected: 'Charts and lists are visible.',
    run: async (page) => {
      await page.getByText('Recent documents').scrollIntoViewIfNeeded()
      await page.waitForTimeout(2500)
      await page.mouse.wheel(0, 500)
      await page.waitForTimeout(2500)
      await page.mouse.wheel(0, -1000)
    },
  },
  {
    chapter: 'Chapter 2 — The dashboard',
    title: 'Going from a figure to the work',
    narration:
      'The figures are shortcuts. Choosing the documents figure opens the library. Choosing the review figure opens her approvals. The dashboard never shows anything the library would not show her, so the numbers always agree with the pages behind them.',
    actions: 'Open the library from the documents figure, then come back.',
    expected: 'The library opens, then the dashboard returns.',
    run: async (page) => {
      await click(page.getByRole('link', { name: /you can see/ }).first())
      await page.getByRole('heading', { name: 'Documents', exact: true }).waitFor()
      await page.waitForTimeout(2200)
      await nav(page, 'Dashboard')
      await page.getByText('Updated').waitFor()
    },
  },
  {
    chapter: 'Chapter 3 — Each person sees their own',
    title: 'Numbers follow access',
    narration:
      'Now Sameer, an ordinary employee, signs in. His dashboard counts only the documents the access rules let him open. Confidential and highly confidential documents that are not his, or not in his department or projects, are not counted, and nothing hints that they exist. The review figure is his own queue.',
    actions: 'Sign out, sign in as an employee and compare the figures.',
    expected: 'The employee sees smaller figures than the administrator.',
    run: async (page) => {
      await signOut(page)
      await signIn(page, sameer)
      await page.getByText('Updated').waitFor()
      await page.waitForTimeout(3000)
    },
  },
  {
    chapter: 'Chapter 4 — Designs',
    title: 'Enterprise Productivity: a dense grid',
    narration:
      'Every design arranges the same information in its own way. Sameer chooses Enterprise Productivity from the Appearance page. It is a dense grid that also shows what is due soon, with retention and review dates in the next thirty days, and a recent activity feed. The activity feed is only filled for people allowed to read the audit log, so for Sameer it explains that it is for administrators.',
    actions: 'Apply Enterprise Productivity and open the dashboard.',
    expected: 'A dense grid with the due soon and activity cards.',
    run: async (page) => {
      await applyDesign(page, 'enterprise-productivity')
      await page.waitForTimeout(2500)
      await page.mouse.wheel(0, 500)
      await page.waitForTimeout(2200)
      await page.mouse.wheel(0, -1000)
    },
  },
  {
    chapter: 'Chapter 4 — Designs',
    title: 'Minimalist Productivity: a focused list',
    narration:
      'Minimalist Productivity shows fewer things in one calm column: the key figures, the recent documents and the review queue. Nothing is hidden from him by the design; it only chooses what to put on the first page.',
    actions: 'Apply Minimalist Productivity and open the dashboard.',
    expected: 'A single focused column.',
    run: async (page) => {
      await applyDesign(page, 'minimalist-productivity')
      await page.waitForTimeout(3500)
    },
  },
  {
    chapter: 'Chapter 4 — Designs',
    title: 'Premium Dark: a hero banner',
    narration:
      'Premium Dark opens with a welcome banner, then the figures, the charts, his review queue and what is due soon, all in the dark theme.',
    actions: 'Apply Premium Dark and open the dashboard.',
    expected: 'A welcome banner and dark cards.',
    run: async (page) => {
      await applyDesign(page, 'premium-dark')
      await page.waitForTimeout(3500)
    },
  },
  {
    chapter: 'Chapter 5 — Summary',
    title: 'Summary',
    narration:
      'To summarize: the dashboard is the first page after sign-in. It shows figures, charts, recent documents, review queues, what is due soon and, for administrators, recent activity. It counts only what each person may see, links to the pages behind each figure, and takes the layout of the design the person has chosen. Dashboards for reports and exports are not part of this release.',
    actions: 'Return to the default design.',
    expected: 'The dashboard is shown in the default design.',
    run: async (page) => {
      await nav(page, 'Appearance')
      await click(page.getByRole('button', { name: 'Reset to default' }))
      await page.waitForTimeout(1200)
      await nav(page, 'Dashboard')
      await page.getByText('Updated').waitFor()
    },
  },
]

recordVideo({ name: NAME, scenes, password, check: assertNoSecret }).catch((error) => {
  console.error(redactor(password)(error))
  process.exit(1)
})
