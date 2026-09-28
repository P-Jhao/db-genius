// 补截：7 语言数据库配置页（修复：init script 不再覆盖 app-locale）
import { chromium } from 'playwright'
import path from 'node:path'

const BASE = 'http://localhost:5173'
const RAW = path.resolve('public/landing/raw')
const LOCALES = ['zh-CN', 'zh-TW', 'en', 'es', 'fr', 'ja', 'ms']
const HIDE_CSS = '.trial-banner{display:none!important}.app-root{--banner-height:0px!important}'

const browser = await chromium.launch()
const ctx = await browser.newContext({
  storageState: '/tmp/dbgenius-dev/state.json',
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
})
await ctx.addInitScript((css) => {
  document.addEventListener('DOMContentLoaded', () => {
    const s = document.createElement('style')
    s.textContent = css
    document.head.appendChild(s)
  })
}, HIDE_CSS)
const page = await ctx.newPage()

for (const code of LOCALES) {
  await page.goto(`${BASE}/admin/db-config?lang=${encodeURIComponent(code)}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(2200)
  await page.addStyleTag({ content: HIDE_CSS }).catch(() => {})
  const lang = await page.evaluate(() => document.documentElement.lang)
  if (lang !== code) throw new Error(`locale mismatch: expect ${code}, got ${lang}`)
  await page.screenshot({ path: path.join(RAW, code, 'db-genius-database-config.png') })
  console.log('config shot:', code)
}

await browser.close()
console.log('CONFIG DONE')
