/** Draws the install icons (PNG) from public/icon.svg with the browser the checks already use. Run after editing the SVG. */
import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire('C:/Users/lenovo/AadiTech/Product/AadiProduct/MultiTenant/Aadi-MultiTenant-Platform/frontend/package.json')
const { chromium } = require('playwright')
const pub = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'public')
const svg = fs.readFileSync(path.join(pub, 'icon.svg'), 'utf8')
const browser = await chromium.launch({ headless: true }).catch(() => chromium.launch({ headless: true, channel: 'chrome' }))
async function png(name, size, { maskable = false } = {}) {
  const page = await browser.newPage({ viewport: { width: size, height: size } })
  // Maskable icons need the artwork inside the central 80%, on a full-bleed background.
  const art = maskable ? `<div style="position:fixed;inset:0;background:#1d4ed8"><div style="position:absolute;inset:12%">${svg.replace('<svg ', '<svg width="100%" height="100%" ').replace('rx="112" fill="#1d4ed8"', 'rx="0" fill="#1d4ed8"')}</div></div>` : `<div style="position:fixed;inset:0">${svg.replace('<svg ', '<svg width="100%" height="100%" ')}</div>`
  await page.setContent(`<body style="margin:0;background:transparent">${art}</body>`)
  await page.screenshot({ path: path.join(pub, name), omitBackground: !maskable })
  await page.close()
}
await png('icon-192.png', 192)
await png('icon-512.png', 512)
await png('icon-maskable-512.png', 512, { maskable: true })
await png('apple-touch-icon.png', 180, { maskable: true })
await browser.close()
console.log('icons written')
