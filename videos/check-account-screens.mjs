/**
 * Browser check of the first-contact and account screens (accept invitation, reset password, join request,
 * Google/Microsoft buttons, change password, two-step verification) against a THROWAWAY demo database.
 * It changes data. The API must run with EMAIL_BACKEND=console and APP_BASE_URL equal to the web address, and
 * write its log to API_LOG, because the check reads the links from the "emails" the API logs.
 * Environment: DMS_WEB_URL (default http://localhost:5174), DEMO_ACCESS_FILE, API_LOG.
 */
import { createRequire } from 'node:module'
import crypto from 'node:crypto'
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
const apiLog = process.env.API_LOG ?? path.join(here, '../services/api/.storage/w2-api.log')
const password = fs.readFileSync(accessFile, 'utf8').match(/Temporary password for every account below: `([^`]+)`/)[1]

let failed = 0
const check = (name, ok, detail = '') => {
  if (!ok) failed += 1
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : ' ' + detail}`)
}
const browser = await chromium.launch({ headless: true }).catch(() => chromium.launch({ headless: true, channel: 'chrome' }))
const errors = []
const fresh = async () => {
  const page = await (await browser.newContext({ viewport: { width: 1500, height: 1000 } })).newPage()
  page.on('pageerror', (e) => errors.push(String(e)))
  return page
}
const text = (page) => page.locator('body').innerText()
async function waitText(page, needle, ms = 8000) {
  await page.waitForFunction((n) => document.body.innerText.includes(n), needle, { timeout: ms }).catch(() => {})
  return (await text(page)).includes(needle)
}
async function signIn(page, email, pw, code) {
  await page.goto(web + '/')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(pw)
  await page.getByRole('button', { name: 'Sign in' }).click()
  if (code) {
    await page.getByLabel('Verification code').fill(code)
    await page.getByRole('button', { name: 'Sign in' }).click()
  }
}
const signedIn = (page) => page.getByRole('heading', { name: 'Documents', exact: true }).waitFor({ timeout: 8000 }).then(() => true).catch(() => false)

/** The newest emailed link (path and token) sent to this address, read from the API's development log. */
async function emailedLink(to, kind) {
  for (let i = 0; i < 20; i++) {
    const log = fs.readFileSync(apiLog, 'utf8')
    const at = log.lastIndexOf(`to=${to} `)
    if (at >= 0) {
      const m = log.slice(at).match(new RegExp(`${web.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/${kind}\\?token=[\\w-]+`))
      if (m) return m[0]
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  return null
}

function totp(secretBase32, offset = 0) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
  let bits = ''
  for (const c of secretBase32.replace(/=+$/, '').toUpperCase()) bits += alphabet.indexOf(c).toString(2).padStart(5, '0')
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)))
  const counter = Buffer.alloc(8)
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000) + offset))
  const h = crypto.createHmac('sha1', key).update(counter).digest()
  const o = h[19] & 15
  return String(((h.readUInt32BE(o) & 0x7fffffff) % 1000000)).padStart(6, '0')
}

// --- sign-in page offers a way in for new people; no provider buttons while none is configured
const p0 = await fresh()
await p0.goto(web + '/')
check('the sign-in page links to asking to join', (await p0.getByRole('link', { name: /Ask to join/ }).count()) === 1)
check('no Google or Microsoft button while none is configured', (await p0.getByRole('button', { name: /Continue with/ }).count()) === 0)

// --- join request -> approval -> accept invitation
const asha = await fresh()
await signIn(asha, 'asha.kulkarni@demo.dms.test', password)
await signedIn(asha)
await asha.getByRole('link', { name: 'People' }).click()
await asha.getByRole('tab', { name: /Join requests/ }).click()
const toggle = asha.getByLabel('Let people ask to join (requests wait here for approval)')
await toggle.waitFor()
if (!(await toggle.isChecked())) await toggle.click()
await asha.waitForFunction(() => document.querySelector('input[type=checkbox]')?.checked === true)
await asha.waitForTimeout(800)

const reg = await fresh()
await reg.goto(web + '/register')
await reg.getByLabel('Organization code').fill('demo-industries')
await reg.getByLabel('Your name').fill('Dev Patel')
await reg.getByLabel('Work email').fill('dev.patel@aaditech.in')
await reg.getByRole('button', { name: 'Send request' }).click()
check('a join request is sent and the answer is the same whatever the organization', await waitText(reg, 'Request sent'))

await asha.getByRole('tab', { name: /Join requests/ }).click()
await asha.reload()
await asha.getByRole('tab', { name: /Join requests/ }).click()
await waitText(asha, 'Dev Patel')
await asha.getByRole('row', { name: /Dev Patel/ }).getByRole('button', { name: 'Approve and invite' }).click()
const inviteLink = await emailedLink('dev.patel@aaditech.in', 'accept-invite')
check('approving sends an email with an invitation link', !!inviteLink)

const dev = await fresh()
await dev.goto(inviteLink.replace(web, web))
await dev.getByLabel('Password', { exact: true }).fill('Short1')
await dev.getByLabel('Repeat password').fill('Short1')
await dev.getByRole('button', { name: 'Join' }).click()
check('a weak password is refused with the reason', await waitText(dev, 'at least') || await waitText(dev, 'Password must be'))
await dev.getByLabel('Password', { exact: true }).fill('Harbour-Lantern-2042')
await dev.getByLabel('Repeat password').fill('Harbour-Lantern-2041')
check('two different passwords are caught before sending', await waitText(dev, 'The two passwords differ'))
await dev.getByLabel('Repeat password').fill('Harbour-Lantern-2042')
await dev.getByRole('button', { name: 'Join' }).click()
check('accepting returns to sign-in with a notice', await waitText(dev, 'Your account is ready'))
await signIn(dev, 'dev.patel@aaditech.in', 'Harbour-Lantern-2042')
check('the new person signs in with the password they chose', await signedIn(dev))
const reuse = await fresh()
await reuse.goto(inviteLink)
await reuse.getByLabel('Password', { exact: true }).fill('Harbour-Lantern-2042')
await reuse.getByLabel('Repeat password').fill('Harbour-Lantern-2042')
await reuse.getByRole('button', { name: 'Join' }).click()
check('the invitation link cannot be used twice', await waitText(reuse, 'invalid, already used or has expired'))

// --- forgot password -> reset
const sam = await fresh()
await sam.goto(web + '/')
await sam.getByLabel('Email').fill('sameer.patil@demo.dms.test')
await sam.getByRole('button', { name: 'Forgot password' }).click()
check('"Forgot password" gives the same answer for any account', await waitText(sam, 'If that account exists'))
const resetLink = await emailedLink('sameer.patil@demo.dms.test', 'reset-password')
check('a reset email is sent', !!resetLink)
await sam.goto(resetLink)
await sam.getByLabel('New password', { exact: true }).fill('Copper-Window-9137')
await sam.getByLabel('Repeat password').fill('Copper-Window-9137')
await sam.getByRole('button', { name: 'Save password' }).click()
check('reset returns to sign-in with a notice', await waitText(sam, 'Your password was changed'))
await signIn(sam, 'sameer.patil@demo.dms.test', password)
check('the old password no longer works', await waitText(sam, 'Invalid email or password'))
await signIn(sam, 'sameer.patil@demo.dms.test', 'Copper-Window-9137')
check('the new password works', await signedIn(sam))
const bad = await fresh()
await bad.goto(web + '/reset-password?token=' + 'x'.repeat(30))
await bad.getByLabel('New password', { exact: true }).fill('Copper-Window-9137')
await bad.getByLabel('Repeat password').fill('Copper-Window-9137')
await bad.getByRole('button', { name: 'Save password' }).click()
check('a made-up reset link is refused', await waitText(bad, 'invalid or has expired'))
await (await fresh()).goto(web + '/accept-invite').then(async () => {})
const noToken = await fresh()
await noToken.goto(web + '/accept-invite')
check('a link without its code explains itself', await waitText(noToken, 'missing its code'))

// --- Google / Microsoft buttons (provider calls are stubbed; no real provider is contacted)
const sso = await fresh()
await sso.route('**/api/v1/auth/sso/providers', (r) => r.fulfill({ json: [{ provider: 'google', client_id: 'test-client.apps.example' }, { provider: 'microsoft', client_id: 'ms-client' }] }))
await sso.goto(web + '/')
await sso.getByRole('button', { name: 'Continue with Google' }).waitFor().catch(() => {})
check('configured providers get a button each', (await sso.getByRole('button', { name: /Continue with/ }).count()) === 2)
let sent = ''
await sso.route('https://accounts.google.com/**', (r) => { sent = r.request().url(); return r.abort() })
await sso.getByRole('button', { name: 'Continue with Google' }).click().catch(() => {})
await sso.waitForTimeout(800)
const u = sent ? new URL(sent) : null
check('Google is asked for an ID token with a nonce and returns to this app', !!u && u.searchParams.get('response_type') === 'id_token' && !!u.searchParams.get('nonce') && u.searchParams.get('redirect_uri') === web + '/sso-callback')
const state = u?.searchParams.get('state')
const nonce = u?.searchParams.get('nonce')
let posted = null
await sso.route('**/api/v1/auth/sso/google', async (r) => {
  posted = r.request().postDataJSON()
  await r.fulfill({ status: 401, json: { detail: 'Sign-in failed' } })
})
await sso.goto(`${web}/sso-callback#id_token=aaa.bbb.ccc&state=${state}`)
check('the callback forwards the token and nonce to the API', await waitText(sso, 'could not be signed in') && posted?.nonce === nonce)
const forged = await fresh()
await forged.goto(`${web}/sso-callback#id_token=aaa.bbb.ccc&state=forged`)
check('an answer that does not match a request from this browser is ignored', await waitText(forged, 'did not match a request'))

// --- change password and two-step verification, signed in
const meera = await fresh()
await signIn(meera, 'meera.joshi@demo.dms.test', password)
await signedIn(meera)
const other = await fresh()
await signIn(other, 'meera.joshi@demo.dms.test', password)
await signedIn(other)
await meera.getByRole('link', { name: 'Account' }).click()
await meera.getByLabel('Current password').fill('not-my-password')
await meera.getByLabel('New password', { exact: true }).fill('Maple-Station-5521')
await meera.getByLabel('Repeat password').fill('Maple-Station-5521')
await meera.getByRole('button', { name: 'Change password' }).click()
check('a wrong current password is refused', await waitText(meera, 'current password is not correct'))
await meera.getByLabel('Current password').fill(password)
await meera.getByRole('button', { name: 'Change password' }).click()
check('the password is changed', await waitText(meera, 'Password changed'))
await meera.getByRole('link', { name: 'Documents' }).click()
check('this browser stays signed in', await signedIn(meera))
await other.reload()
check('another browser is signed out', await other.getByRole('button', { name: 'Sign in' }).waitFor({ timeout: 8000 }).then(() => true).catch(() => false))

await meera.getByRole('link', { name: 'Account' }).click()
await meera.getByRole('button', { name: 'Set up two-step verification' }).click()
const secret = (await meera.locator('p, span').filter({ hasText: /^[A-Z2-7]{16,}$/ }).first().innerText()).trim()
check('setup shows a QR picture and the key', (await meera.getByRole('img', { name: /QR code/ }).count()) === 1 && secret.length >= 16)
await meera.getByLabel('Code').fill('000000')
await meera.getByRole('button', { name: 'Turn on' }).click()
check('a wrong code does not turn it on', await waitText(meera, 'Two-step verification: off') && !(await text(meera)).includes('recovery codes'))
// each code can be used once and later codes must be newer, so the three uses below take the previous, current and next 30-second codes
await meera.getByLabel('Code').fill(totp(secret, -1))
await meera.getByRole('button', { name: 'Turn on' }).click()
check('the right code turns it on and shows recovery codes once', (await waitText(meera, 'Keep these recovery codes')) && (await waitText(meera, 'Two-step verification: on')))
await meera.getByRole('button', { name: 'I have saved them' }).click()
check('the codes are hidden after being saved', !(await text(meera)).includes('Keep these recovery codes'))

const again = await fresh()
await again.goto(web + '/')
await again.getByLabel('Email').fill('meera.joshi@demo.dms.test')
await again.getByLabel('Password').fill('Maple-Station-5521')
await again.getByRole('button', { name: 'Sign in' }).click()
check('sign-in now asks for a code', await waitText(again, 'Enter the 6-digit code'))
await again.getByLabel('Verification code').fill(totp(secret, 0))
await again.getByRole('button', { name: 'Sign in' }).click()
check('and accepts the right one', await signedIn(again))

await meera.getByRole('button', { name: 'Turn off' }).click()
await meera.getByRole('textbox', { name: 'Password', exact: true }).fill('Maple-Station-5521')
await meera.getByLabel('Code').fill(totp(secret, 1))
await meera.getByRole('button', { name: 'Turn off' }).last().click()
check('it can be turned off with the password and a code', await waitText(meera, 'Two-step verification: off'))

check('no script errors', errors.length === 0, errors.slice(0, 3).join(' | '))
await browser.close()
console.log(failed ? `${failed} check(s) FAILED` : 'ALL CHECKS PASSED')
process.exit(failed ? 1 : 0)
