/**
 * Video 04: administration (Sprint W2b): people and roles, invitations and join requests, the audit
 * log and search index, categories with rules and fields, tags, and organization editing.
 * Uses the shared pipeline in lib.mjs. It changes data, so run it on a fresh RECORDING database,
 * not on the demo you browse. Environment: DMS_WEB_URL, DEMO_ACCESS_FILE.
 */
import { click, loadPassword, origin, recordVideo, redactor } from './lib.mjs'

const NAME = '04-dms-administration'
const password = loadPassword()
const asha = 'asha.kulkarni@demo.dms.test'

async function signIn(page, email) {
  await page.goto(origin + '/', { waitUntil: 'domcontentloaded' })
  await page.getByLabel('Email').fill(email)
  const field = page.getByLabel('Password')
  await field.fill(password)
  if ((await field.getAttribute('type')) !== 'password') throw new Error('The password field is not masked')
  await click(page.getByRole('button', { name: 'Sign in' }))
  await page.getByRole('heading', { name: 'Documents', exact: true }).waitFor()
}
const nav = (page, name) => click(page.getByRole('link', { name }).first())
const dialog = (page) => page.getByRole('dialog')
const nameField = (page) => page.getByRole('textbox', { name: /^Name/ })
async function pick(page, label, option, exact = false) {
  await click(page.getByLabel(label, { exact: true }))
  await click(page.getByRole('option', { name: option, exact }))
}
async function assertNoSecret(page) {
  if ((await page.locator('body').innerText()).includes(password)) throw new Error('The demo password is visible on screen')
}

const scenes = [
  {
    chapter: 'Chapter 1 — Introduction',
    title: 'What this video covers',
    narration:
      'This video shows the administration screens of the D M S web application. An organization administrator can manage people and their roles, review what has happened, define the categories and rules for documents, and maintain the organization structure, all from the browser. It uses a recording copy of the demo organization.',
    actions: 'Open the sign-in page.',
    expected: 'The sign-in form is visible.',
    run: async (page) => {
      await page.goto(origin + '/', { waitUntil: 'domcontentloaded' })
      await page.getByRole('button', { name: 'Sign in' }).waitFor()
    },
  },
  {
    chapter: 'Chapter 2 — People',
    title: 'Employees and roles',
    narration:
      'Asha is the organization administrator. The People page lists every employee with their roles. Roles decide which actions a person may attempt. Which individual documents they can open is decided separately by classification, department, project and sharing. She gives Neha the Reviewer role, and the change applies at once. She can take it away again the same way.',
    actions: 'Sign in, open People, give and remove a role.',
    expected: 'The Reviewer role appears and disappears next to the person.',
    run: async (page) => {
      await signIn(page, asha)
      await nav(page, 'People')
      await page.getByRole('row', { name: /Neha Shah/ }).waitFor()
      await click(page.getByRole('row', { name: /Neha Shah/ }).getByRole('button', { name: 'Roles' }))
      await click(dialog(page).getByRole('checkbox', { name: /Reviewer/ }))
      await page.waitForTimeout(1800)
      await click(dialog(page).getByRole('checkbox', { name: /Reviewer/ }))
      await page.waitForTimeout(1500)
      await click(dialog(page).getByRole('button', { name: 'Close' }).last())
    },
  },
  {
    chapter: 'Chapter 2 — People',
    title: 'The last administrator is protected',
    narration:
      'There is a safeguard: an organization must always keep at least one administrator. If Asha tries to remove her own administrator role while she is the only one, the system refuses and explains why.',
    actions: 'Try to remove the only administrator role.',
    expected: 'A message says the organization must keep at least one administrator.',
    run: async (page) => {
      await click(page.getByRole('row', { name: /Asha Kulkarni/ }).getByRole('button', { name: 'Roles' }))
      await click(dialog(page).getByRole('checkbox', { name: /org_admin|Organization administrator/i }))
      await page.getByText('at least one administrator').waitFor()
      await page.waitForTimeout(2200)
      await click(dialog(page).getByRole('button', { name: 'Close' }).last())
    },
  },
  {
    chapter: 'Chapter 3 — Joining the organization',
    title: 'Invitations',
    narration:
      'To bring someone in, Asha chooses Invite someone, enters their work email and name, and picks a role. They receive a single use link to set a password. The Invitations tab shows who has not accepted yet. An invitation can be sent again, which makes the earlier link stop working, or withdrawn.',
    actions: 'Invite a person, then resend and withdraw the invitation.',
    expected: 'The invitation is listed, then removed.',
    run: async (page) => {
      await click(page.getByRole('button', { name: 'Invite someone' }))
      await page.getByLabel('Work email').fill('new.person@aaditech.in')
      await page.getByLabel('Full name').fill('Rahul Verma')
      await pick(page, 'Role', 'reviewer')
      await page.waitForTimeout(900)
      await click(page.getByRole('button', { name: 'Send invitation' }))
      await click(page.getByRole('tab', { name: /Invitations/ }))
      await page.getByRole('row', { name: /Rahul Verma/ }).waitFor()
      await page.waitForTimeout(1500)
      await click(page.getByRole('row', { name: /Rahul Verma/ }).getByRole('button', { name: 'Resend' }))
      await page.getByText('sent again').waitFor()
      await page.waitForTimeout(1500)
      await click(page.getByRole('row', { name: /Rahul Verma/ }).getByRole('button', { name: 'Withdraw' }))
      await page.getByText('The invitation was withdrawn.').waitFor()
    },
  },
  {
    chapter: 'Chapter 3 — Joining the organization',
    title: 'Join requests',
    narration:
      'Organizations can also let people ask to join. This is off by default. Asha switches it on, and a person fills in the public request form. For this recording that request was submitted on their behalf. The request waits for her decision. Approving it sends an invitation. Nobody gets in without an administrator saying yes.',
    actions: 'Allow join requests, receive one and approve it.',
    expected: 'The request is approved and an invitation is sent.',
    run: async (page) => {
      await click(page.getByRole('tab', { name: /Join requests/ }))
      await click(page.getByRole('checkbox', { name: /Let people ask to join/ }))
      await page.waitForTimeout(1200)
      await page.evaluate(() =>
        fetch('/api/v1/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tenant_slug: 'demo-industries', email: 'walk.in@aaditech.in', full_name: 'Kavita Rao' }) }),
      )
      await page.reload()
      await click(page.getByRole('tab', { name: /Join requests/ }))
      await page.getByRole('row', { name: /Kavita Rao/ }).waitFor()
      await page.waitForTimeout(1500)
      await click(page.getByRole('row', { name: /Kavita Rao/ }).getByRole('button', { name: 'Approve and invite' }))
      await page.getByText('Approved. An invitation was sent.').waitFor()
    },
  },
  {
    chapter: 'Chapter 3 — Joining the organization',
    title: 'Lost device',
    narration:
      'If someone loses the phone they use for two step verification, an administrator can reset it. The system explains what this does and records the reset as a privileged action. The person then signs in with their password and sets two step verification up again.',
    actions: 'Open Reset two-step for an employee and confirm.',
    expected: 'A confirmation message appears.',
    run: async (page) => {
      await click(page.getByRole('tab', { name: 'Employees' }))
      await click(page.getByRole('row', { name: /Priya Nair/ }).getByRole('button', { name: 'Reset two-step' }))
      await page.waitForTimeout(2500)
      await click(page.getByRole('button', { name: 'Reset two-step verification', exact: true }))
      await page.getByText('Two-step verification was reset.').waitFor()
    },
  },
  {
    chapter: 'Chapter 4 — Activity',
    title: 'The audit log and search index',
    narration:
      'The Activity page is the audit log: who did what and when, including everything we just did, with the people named. It can be filtered by action and date. Privileged actions are marked. The Search index tab shows how document text indexing is going, and lets an administrator process the queue or retry failures.',
    actions: 'Open Activity, filter the log, open the search index tab and process the queue.',
    expected: 'The log lists recent events; the index tab reports the processed queue.',
    run: async (page) => {
      await nav(page, 'Activity')
      await page.getByRole('heading', { name: 'Activity' }).waitFor()
      await page.getByText('rbac.role_assigned').first().waitFor()
      await page.waitForTimeout(2500)
      await page.getByLabel(/Action \(exact/).fill('invitation.created')
      await click(page.getByRole('button', { name: 'Filter' }))
      await page.waitForTimeout(2200)
      await click(page.getByRole('tab', { name: 'Search index' }))
      await click(page.getByRole('button', { name: 'Process the queue now' }))
      await page.getByText('Processed the queue').waitFor()
    },
  },
  {
    chapter: 'Chapter 5 — Categories and rules',
    title: 'Creating a category with rules',
    narration:
      'Categories are the kinds of document the organization keeps, and each carries its own rules. Asha creates HR Letters. It is confidential by default and needs review before release, with one review step held by anyone with the Reviewer role. People must link each letter to a department, only P D F and Word files are allowed, it is kept for two years, and the form asks for a letter reference.',
    actions: 'Create a category with a review step, a required link, allowed types, retention and a field.',
    expected: 'HR Letters appears in the list.',
    run: async (page) => {
      await nav(page, 'Categories')
      await page.getByRole('heading', { name: 'Categories and tags' }).waitFor()
      await click(page.getByRole('button', { name: 'New category' }))
      await nameField(page).fill('HR Letters')
      await pick(page, 'Default classification', 'Confidential', true)
      await click(page.getByLabel('Documents are reviewed before they are released'))
      await click(page.getByRole('button', { name: 'Add a step' }))
      await pick(page, 'Role', 'reviewer')
      await click(page.getByLabel('department'))
      await page.getByLabel('Allowed file types (blank = all)').fill('pdf, docx')
      await page.getByLabel('Keep for (days)').fill('730')
      await click(page.getByRole('button', { name: 'Add a field' }))
      await page.getByLabel('Key').fill('letter_ref')
      await page.getByLabel('Label', { exact: true }).fill('Letter reference')
      await page.waitForTimeout(1500)
      await click(page.getByRole('button', { name: 'Create category' }))
      await page.getByRole('row', { name: /HR Letters/ }).waitFor()
    },
  },
  {
    chapter: 'Chapter 5 — Categories and rules',
    title: 'Changing the rules safely',
    narration:
      'Rules can change. Asha reopens the category and shortens the retention period. Saving does not rewrite history: it publishes a new version of the rules. Documents already filed keep the rules they were created under, and new documents follow the new version.',
    actions: 'Reopen the rules, change retention and publish a new version.',
    expected: 'The category shows rules version 2.',
    run: async (page) => {
      await click(page.getByRole('row', { name: /HR Letters/ }).getByRole('button', { name: 'Rules' }))
      await page.getByText('Saving publishes a new version').waitFor()
      await page.waitForTimeout(1800)
      await page.getByLabel('Keep for (days)').fill('365')
      await page.waitForTimeout(1200)
      await click(page.getByRole('button', { name: 'Publish new version' }))
      await page.getByRole('row', { name: /HR Letters/ }).getByText('v2').waitFor()
    },
  },
  {
    chapter: 'Chapter 5 — Categories and rules',
    title: 'Tags',
    narration:
      'Tags are free labels on documents. Asha adds a standard tag called Urgent, and can switch tags on or off. The built in tags, such as Pending and Approved, cannot be changed. A switch decides whether employees may create their own tags.',
    actions: 'Add a standard tag and switch it off.',
    expected: 'The tag appears and then shows as inactive.',
    run: async (page) => {
      await click(page.getByRole('tab', { name: 'Tags' }))
      await page.getByLabel('New standard tag').fill('Urgent')
      await click(page.getByRole('button', { name: 'Add tag' }))
      await page.getByRole('row', { name: /Urgent/ }).waitFor()
      await page.waitForTimeout(1500)
      await click(page.getByRole('row', { name: /Urgent/ }).getByRole('button', { name: 'Turn off' }))
      await page.getByRole('row', { name: /Urgent/ }).getByText('Inactive').waitFor()
    },
  },
  {
    chapter: 'Chapter 6 — Organization',
    title: 'Departments, projects and employees',
    narration:
      'The Organization page now has editing for administrators. Asha adds a Legal department, makes Rohan its manager and renames it. Managers see their department documents and can be review steps. On a project she adds Neha and ends her membership the same day. And she moves Neha to the new department in her employee details. Nothing is ever deleted: items are switched off and their history is kept.',
    actions: 'Add and rename a department, add and end a project member, change an employee department.',
    expected: 'The department exists with its manager; the employee shows the new department.',
    run: async (page) => {
      await nav(page, 'Organization')
      await click(page.getByRole('button', { name: 'Add', exact: true }))
      await nameField(page).fill('Legal')
      await page.getByLabel('Short code').fill('LEG')
      await pick(page, 'Manager', 'Rohan Deshmukh')
      await page.waitForTimeout(1200)
      await click(page.getByRole('button', { name: 'Save', exact: true }))
      await page.getByRole('row', { name: /Legal/ }).getByText('Rohan Deshmukh').waitFor()
      await click(page.getByRole('row', { name: /Legal/ }).getByRole('button', { name: 'Edit' }))
      await nameField(page).fill('Legal and Compliance')
      await click(page.getByRole('button', { name: 'Save', exact: true }))
      await page.getByText('Legal and Compliance').first().waitFor()
      await click(page.getByRole('tab', { name: 'Projects' }))
      await click(page.getByRole('row', { name: /Apollo/ }).getByRole('button', { name: 'People' }))
      await pick(page, 'Add a person', 'Neha Shah')
      await click(page.getByRole('button', { name: 'Add', exact: true }))
      await page.getByText('Neha Shah ·').waitFor()
      await page.waitForTimeout(1500)
      await click(page.getByRole('button', { name: 'End today' }).last())
      await page.getByText(' · ends ').waitFor()
      await page.waitForTimeout(1200)
      await click(dialog(page).getByRole('button', { name: 'Close' }).last())
      await click(page.getByRole('tab', { name: 'Employees' }))
      await click(page.getByRole('row', { name: /Neha Shah/ }).getByRole('button', { name: 'Edit' }))
      await pick(page, 'Department', 'Legal and Compliance')
      await page.waitForTimeout(1000)
      await click(page.getByRole('button', { name: 'Save', exact: true }))
      await page.getByRole('row', { name: /Neha Shah/ }).getByText('Legal and Compliance').waitFor()
    },
  },
  {
    chapter: 'Chapter 7 — Summary',
    title: 'Summary',
    narration:
      'To summarize: people and roles with a protected last administrator, invitations and join requests, two step reset, a searchable audit log, categories with versioned rules, review steps and fields, tags, and a fully editable organization structure. Still to come in the web application are the account pages for accepting an invitation, resetting a password, and setting up two step verification.',
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
