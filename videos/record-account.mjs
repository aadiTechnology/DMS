/**
 * Video 05: account and first-contact pages (Sprint W2c): asking to join, accepting an invitation, resetting a
 * password, the Google and Microsoft buttons, changing a password and two-step verification.
 * Uses the shared pipeline in lib.mjs. It changes data, so run it on a fresh RECORDING database whose API runs
 * with EMAIL_BACKEND=console and APP_BASE_URL equal to the web address (the emailed links are read from the
 * API's development log). Environment: DMS_WEB_URL, DEMO_ACCESS_FILE, API_LOG.
 */
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { click, loadPassword, origin, recordVideo, redactor, repo } from './lib.mjs'

const NAME = '05-dms-account-and-sign-in'
const password = loadPassword()
const apiLog = process.env.API_LOG ?? path.join(repo, 'services/api/.storage/w2-api.log')
const asha = 'asha.kulkarni@demo.dms.test'
const NEW_EMAIL = 'dev.patel@aaditech.in'
const NEW_PASSWORD = 'Harbour-Lantern-2042'
const RESET_PASSWORD = 'Copper-Window-9137'
const CHANGED_PASSWORD = 'Maple-Station-5521'

const nav = (page, name) => click(page.getByRole('link', { name }).first())
async function assertNoSecret(page) {
  if ((await page.locator('body').innerText()).includes(password)) throw new Error('The demo password is visible on screen')
}
async function signIn(page, email, pw, code) {
  await page.goto(origin + '/', { waitUntil: 'domcontentloaded' })
  await page.getByLabel('Email').fill(email)
  const field = page.getByLabel('Password')
  await field.fill(pw)
  if ((await field.getAttribute('type')) !== 'password') throw new Error('The password field is not masked')
  await click(page.getByRole('button', { name: 'Sign in' }))
  if (code) {
    await page.getByLabel('Verification code').fill(code())
    await click(page.getByRole('button', { name: 'Sign in' }))
  }
  await page.getByRole('heading', { name: /^(Dashboard|Documents)$/ }).waitFor()
  if (await page.getByRole('heading', { name: 'Dashboard', exact: true }).count()) { await page.getByRole('link', { name: 'Documents' }).first().click(); await page.getByRole('heading', { name: 'Documents', exact: true }).waitFor() }
}
const signOut = async (page) => {
  await click(page.getByRole('button', { name: 'Sign out' }))
  await page.getByRole('button', { name: 'Sign in' }).waitFor()
}

/** The newest emailed link of this kind sent to this address, read from the API's development log. */
async function emailedLink(to, kind) {
  const escaped = origin.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  for (let i = 0; i < 30; i += 1) {
    const log = fs.readFileSync(apiLog, 'utf8')
    const at = log.lastIndexOf(`to=${to} `)
    const match = at >= 0 ? log.slice(at).match(new RegExp(`${escaped}/${kind}\\?token=[\\w-]+`)) : null
    if (match) return match[0]
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error(`No ${kind} email was logged for ${to}`)
}

/** Authenticator codes work once and must be newer than the last one used; pick one that is. */
function codeSource(secretBase32) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
  let bits = ''
  for (const c of secretBase32.replace(/=+$/, '').toUpperCase()) bits += alphabet.indexOf(c).toString(2).padStart(5, '0')
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)))
  const at = (step) => {
    const counter = Buffer.alloc(8)
    counter.writeBigUInt64BE(BigInt(step))
    const h = crypto.createHmac('sha1', key).update(counter).digest()
    const o = h[19] & 15
    return String((h.readUInt32BE(o) & 0x7fffffff) % 1000000).padStart(6, '0')
  }
  let last = 0
  return () => {
    const now = Math.floor(Date.now() / 30000)
    const step = Math.max(now - 1, last + 1)
    if (step > now + 1) throw new Error('No unused authenticator code is available yet')
    last = step
    return at(step)
  }
}
let nextCode

const scenes = [
  {
    chapter: 'Chapter 1 — Introduction',
    title: 'What this video covers',
    narration:
      'This video shows how people get into the D M S web application and look after their own account. It covers asking to join, accepting an invitation, resetting a forgotten password, signing in with Google or Microsoft, changing a password, and two step verification. It uses a recording copy of the demo organization, and the emails that the system would send are read from its development log.',
    actions: 'Open the sign-in page.',
    expected: 'The sign-in page shows the Ask to join link.',
    run: async (page) => {
      await page.goto(origin + '/', { waitUntil: 'domcontentloaded' })
      await page.getByRole('link', { name: /Ask to join/ }).waitFor()
    },
  },
  {
    chapter: 'Chapter 2 — Joining',
    title: 'Allowing join requests',
    narration:
      'By default nobody can ask to join an organization. Asha, the administrator, opens People, then Join requests, and switches on the option that lets people ask. Then she signs out.',
    actions: 'Sign in as the administrator, allow join requests, sign out.',
    expected: 'The option is on and the sign-in page returns.',
    run: async (page) => {
      await signIn(page, asha, password)
      await nav(page, 'People')
      await click(page.getByRole('tab', { name: /Join requests/ }))
      await click(page.getByRole('checkbox', { name: /Let people ask to join/ }))
      await page.waitForTimeout(1800)
      await signOut(page)
    },
  },
  {
    chapter: 'Chapter 2 — Joining',
    title: 'Asking to join',
    narration:
      'A new colleague, Dev, chooses Ask to join on the sign-in page. He enters the organization code, his name and his work email. The answer is the same whether or not the organization exists or allows requests, so the form cannot be used to find out who has an account.',
    actions: 'Fill in and send the join request.',
    expected: 'A confirmation says the request was sent.',
    run: async (page) => {
      await click(page.getByRole('link', { name: /Ask to join/ }))
      await page.getByLabel('Organization code').fill('demo-industries')
      await page.getByLabel('Your name').fill('Dev Patel')
      await page.getByLabel('Work email').fill(NEW_EMAIL)
      await page.waitForTimeout(900)
      await click(page.getByRole('button', { name: 'Send request' }))
      await page.getByText('Request sent').waitFor()
    },
  },
  {
    chapter: 'Chapter 2 — Joining',
    title: 'Approving the request',
    narration:
      'Asha sees the request waiting under Join requests and approves it. That sends Dev an invitation email with a link that works once.',
    actions: 'Sign in as the administrator and approve the request.',
    expected: 'The request is approved and an invitation is sent.',
    run: async (page) => {
      await signIn(page, asha, password)
      await nav(page, 'People')
      await click(page.getByRole('tab', { name: /Join requests/ }))
      await click(page.getByRole('row', { name: /Dev Patel/ }).getByRole('button', { name: 'Approve and invite' }))
      await page.getByText('Approved. An invitation was sent.').waitFor()
      await page.waitForTimeout(1200)
      await signOut(page)
    },
  },
  {
    chapter: 'Chapter 3 — Accepting an invitation',
    title: 'Choosing a password',
    narration:
      'Dev opens the link from his email. He must choose a password. A weak one is refused with the reason, and the two boxes must match before anything is sent. Once he joins, he is taken back to sign-in with a short confirmation, and signs in with the password he chose.',
    actions: 'Open the invitation link, try a weak password, then a good one, then sign in.',
    expected: 'The new person reaches the document library.',
    run: async (page) => {
      await page.goto(await emailedLink(NEW_EMAIL, 'accept-invite'), { waitUntil: 'domcontentloaded' })
      await page.getByLabel('Password', { exact: true }).fill('Short1')
      await page.getByLabel('Repeat password').fill('Short1')
      await page.waitForTimeout(900)
      await click(page.getByRole('button', { name: 'Join' }))
      await page.getByText(/Password must be/).waitFor()
      await page.waitForTimeout(1500)
      await page.getByLabel('Password', { exact: true }).fill(NEW_PASSWORD)
      await page.getByLabel('Repeat password').fill(NEW_PASSWORD + '1')
      await page.getByText('The two passwords differ').waitFor()
      await page.waitForTimeout(1500)
      await page.getByLabel('Repeat password').fill(NEW_PASSWORD)
      await click(page.getByRole('button', { name: 'Join' }))
      await page.getByText('Your account is ready').waitFor()
      await page.waitForTimeout(1500)
      await signIn(page, NEW_EMAIL, NEW_PASSWORD)
      await page.waitForTimeout(1200)
      await signOut(page)
    },
  },
  {
    chapter: 'Chapter 3 — Accepting an invitation',
    title: 'A link works once',
    narration:
      'Invitation links are single use. If Dev opens the same link again, the page says it is invalid, already used or expired, and tells him to ask the administrator for a new one.',
    actions: 'Open the used link again and submit.',
    expected: 'A message says the link is invalid, used or expired.',
    run: async (page) => {
      await page.goto(await emailedLink(NEW_EMAIL, 'accept-invite'), { waitUntil: 'domcontentloaded' })
      await page.getByLabel('Password', { exact: true }).fill(NEW_PASSWORD)
      await page.getByLabel('Repeat password').fill(NEW_PASSWORD)
      await click(page.getByRole('button', { name: 'Join' }))
      await page.getByText(/invalid, already used or has expired/).waitFor()
    },
  },
  {
    chapter: 'Chapter 4 — Forgotten password',
    title: 'Resetting a password',
    narration:
      'Sameer has forgotten his password. On the sign-in page he types his email and chooses Forgot password. The answer is always the same, so it never reveals whether an account exists. The email contains a link, and the new password is chosen on a page like the one for invitations. A reset signs him out everywhere else. His old password stops working at once.',
    actions: 'Request a reset, follow the link, choose a new password, sign in.',
    expected: 'Sameer signs in with the new password.',
    run: async (page) => {
      const sameer = 'sameer.patil@demo.dms.test'
      await page.goto(origin + '/', { waitUntil: 'domcontentloaded' })
      await page.getByLabel('Email').fill(sameer)
      await click(page.getByRole('button', { name: 'Forgot password' }))
      await page.getByText('If that account exists').waitFor()
      await page.waitForTimeout(1500)
      await page.goto(await emailedLink(sameer, 'reset-password'), { waitUntil: 'domcontentloaded' })
      await page.getByLabel('New password', { exact: true }).fill(RESET_PASSWORD)
      await page.getByLabel('Repeat password').fill(RESET_PASSWORD)
      await page.waitForTimeout(900)
      await click(page.getByRole('button', { name: 'Save password' }))
      await page.getByText('Your password was changed').waitFor()
      await page.waitForTimeout(1200)
      await signIn(page, sameer, RESET_PASSWORD)
      await page.waitForTimeout(1000)
      await signOut(page)
    },
  },
  {
    chapter: 'Chapter 5 — Google and Microsoft',
    title: 'Google and Microsoft buttons',
    narration:
      'Organizations can also let people sign in with Google or Microsoft. The buttons appear only for providers the server has been set up with. This recording uses a test setting so the buttons are visible. Real sign-in needs the organization to register with each provider, which has not been done yet. The account must already exist here: signing in with a provider never creates one.',
    actions: 'Show the provider buttons using a test setting.',
    expected: 'Two buttons appear on the sign-in page.',
    run: async (page) => {
      await page.route('**/api/v1/auth/sso/providers', (r) =>
        r.fulfill({ json: [{ provider: 'google', client_id: 'test' }, { provider: 'microsoft', client_id: 'test' }] }),
      )
      await page.goto(origin + '/', { waitUntil: 'domcontentloaded' })
      await page.getByRole('button', { name: 'Continue with Google' }).waitFor()
      await page.getByRole('button', { name: 'Continue with Microsoft' }).waitFor()
    },
  },
  {
    chapter: 'Chapter 6 — Your account',
    title: 'Changing your password',
    narration:
      'Signed in, Meera opens Account and changes her password. She must enter the current one, and a wrong one is refused. When it works, her other browsers and devices are signed out, while this one stays signed in.',
    actions: 'Sign in, try a wrong current password, then change it properly.',
    expected: 'A confirmation says the password was changed.',
    run: async (page) => {
      await page.unroute('**/api/v1/auth/sso/providers')
      await signIn(page, 'meera.joshi@demo.dms.test', password)
      await nav(page, 'Account')
      await page.getByLabel('Current password').fill('not-my-password')
      await page.getByLabel('New password', { exact: true }).fill(CHANGED_PASSWORD)
      await page.getByLabel('Repeat password').fill(CHANGED_PASSWORD)
      await page.waitForTimeout(900)
      await click(page.getByRole('button', { name: 'Change password' }))
      await page.getByText('current password is not correct').waitFor()
      await page.waitForTimeout(1500)
      await page.getByLabel('Current password').fill(password)
      await click(page.getByRole('button', { name: 'Change password' }))
      await page.getByText('Password changed.').waitFor()
    },
  },
  {
    chapter: 'Chapter 6 — Your account',
    title: 'Two step verification',
    narration:
      'Two step verification adds a six digit code from an authenticator app. Meera chooses Set up, scans the picture or types the key, and confirms with a code. The system then shows recovery codes, once, to keep somewhere safe. If she loses her phone, each one works once, and an administrator can also reset it.',
    actions: 'Set up two step verification and confirm with a code.',
    expected: 'Two step verification is on and recovery codes are shown once.',
    run: async (page) => {
      await click(page.getByRole('button', { name: 'Set up two-step verification' }))
      await page.getByRole('img', { name: /QR code/ }).waitFor()
      const secret = (await page.locator('p, span').filter({ hasText: /^[A-Z2-7]{16,}$/ }).first().innerText()).trim()
      nextCode = codeSource(secret)
      await page.waitForTimeout(2500)
      await page.getByLabel('Code').fill(nextCode())
      await click(page.getByRole('button', { name: 'Turn on' }))
      await page.getByText('Keep these recovery codes').waitFor()
      await page.waitForTimeout(3000)
      await click(page.getByRole('button', { name: 'I have saved them' }))
    },
  },
  {
    chapter: 'Chapter 6 — Your account',
    title: 'Signing in with a code, and turning it off',
    narration:
      'From now on, signing in asks for the code after the password. A code works only once, so after turning this on she may need to wait for the next one. She can turn two step verification off again, which needs her password and a current code.',
    actions: 'Sign out, sign in with a code, then turn it off.',
    expected: 'Sign-in asks for a code, and two step verification ends up off.',
    run: async (page) => {
      await signOut(page)
      await page.getByLabel('Email').fill('meera.joshi@demo.dms.test')
      await page.getByLabel('Password').fill(CHANGED_PASSWORD)
      await click(page.getByRole('button', { name: 'Sign in' }))
      await page.getByText('Enter the 6-digit code').waitFor()
      await page.waitForTimeout(1200)
      await page.getByLabel('Verification code').fill(nextCode())
      await click(page.getByRole('button', { name: 'Sign in' }))
      await page.getByRole('heading', { name: 'Documents', exact: true }).waitFor()
      await nav(page, 'Account')
      await click(page.getByRole('button', { name: 'Turn off' }))
      await page.getByRole('textbox', { name: 'Password', exact: true }).fill(CHANGED_PASSWORD)
      await page.getByLabel('Code').fill(nextCode())
      await page.waitForTimeout(900)
      await click(page.getByRole('button', { name: 'Turn off' }).last())
      await page.getByText('Two-step verification: off').waitFor()
    },
  },
  {
    chapter: 'Chapter 7 — Summary',
    title: 'Summary',
    narration:
      'To summarize: people can ask to join, accept invitations, reset a forgotten password, and manage their own password and two step verification entirely in the browser. Provider sign-in is built and waits for the organization to register with Google and Microsoft. Next in the plan are notifications.',
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
