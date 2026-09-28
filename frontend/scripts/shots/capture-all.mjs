// 主截图脚本：7 语言 × 3 场景
// 1) zh-CN 跑一次实时查询（保留瞬时步骤卡片于 pinia store）
// 2) 同会话内 UI 切换语言，逐语言截「意图识别」（步骤卡片时间线）
// 3) 打开 2026/7/31 历史会话（summary 内含 执行 SQL + 结果表），逐语言截「AI SQL 查询」
// 4) 逐语言截「数据库配置」页
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'

const BASE = 'http://localhost:5173'
const RAW = path.resolve('public/landing/raw')
const QUERY = '查询博客数据库里所有文章的标题和发布时间，按时间倒序排列'
const OLD_CONV_DATE = '2026/7/31'

const LOCALES = [
  ['zh-CN', '简体中文'],
  ['zh-TW', '繁體中文'],
  ['en', 'English'],
  ['es', 'Español'],
  ['fr', 'Français'],
  ['ja', '日本語'],
  ['ms', 'Bahasa Melayu'],
]

const HIDE_CSS = '.trial-banner{display:none!important}.app-root{--banner-height:0px!important}'

for (const [code] of LOCALES) fs.mkdirSync(path.join(RAW, code), { recursive: true })

const browser = await chromium.launch()
const ctx = await browser.newContext({
  storageState: '/tmp/dbgenius-dev/state.json',
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
})
await ctx.addInitScript((css) => {
  localStorage.setItem('app-locale', 'zh-CN')
  document.addEventListener('DOMContentLoaded', () => {
    const s = document.createElement('style')
    s.textContent = css
    document.head.appendChild(s)
  })
}, HIDE_CSS)
const page = await ctx.newPage()
page.setDefaultTimeout(20000)

async function hideBanner() {
  await page.addStyleTag({ content: HIDE_CSS }).catch(() => {})
}

async function switchLocale(code, nativeName) {
  await page.locator('.lang-switcher').first().click()
  await page.waitForTimeout(400)
  await page.locator('.arco-dropdown-option', { hasText: nativeName }).first().click()
  await page.waitForTimeout(1200)
  const lang = await page.evaluate(() => document.documentElement.lang)
  if (lang !== code) throw new Error(`locale switch failed: expect ${code}, got ${lang}`)
}

async function scrollChatTop() {
  await page.evaluate(() => {
    const c = document.querySelector('.chat-messages')
    if (c) c.scrollTop = 0
  })
  await page.waitForTimeout(600)
}

async function scrollChatToText(text, abovePx) {
  const ok = await page.evaluate(
    ({ text, abovePx }) => {
      const c = document.querySelector('.chat-messages')
      if (!c) return false
      const els = [...c.querySelectorAll('pre, code, p, div, td')]
      const el = els.find((e) => e.childElementCount === 0 && (e.textContent || '').includes(text))
      if (!el) return false
      const cRect = c.getBoundingClientRect()
      const r = el.getBoundingClientRect()
      c.scrollTop += r.top - cRect.top - abovePx
      return true
    },
    { text, abovePx }
  )
  await page.waitForTimeout(600)
  return ok
}

// ---------- 登录态检查 ----------
await page.goto(`${BASE}/admin/chat`, { waitUntil: 'networkidle' })
await page.waitForTimeout(2000)
if (page.url().includes('/login')) {
  await page.getByRole('button', { name: /登 录|登录/ }).click()
  await page.waitForURL('**/admin/**', { timeout: 20000 })
  await page.waitForTimeout(2000)
  await ctx.storageState({ path: '/tmp/dbgenius-dev/state.json' })
}
await hideBanner()

// ---------- 1) 实时查询 ----------
await page.locator('.db-selector .arco-select-view').first().click()
await page.waitForTimeout(800)
await page.locator('.arco-select-dropdown .arco-select-option').first().click()
await page.waitForTimeout(500)
await page.locator('textarea').fill(QUERY)
await page.getByRole('button', { name: /发 送|发送/ }).click()
console.log('query sent')

// 等流式结束（停止按钮消失）
await page.locator('button:has-text("停止")').waitFor({ state: 'visible', timeout: 20000 }).catch(() => {})
await page.locator('button:has-text("停止")').waitFor({ state: 'hidden', timeout: 120000 })
await page.mouse.move(720, 300)
await page.waitForTimeout(1500)
const stepCount = await page.locator('.step-card').count()
console.log('live run done, step cards:', stepCount)
if (stepCount < 3) throw new Error('step cards missing, abort')

// ---------- 2) 逐语言截「意图识别」 ----------
for (const [code, nativeName] of LOCALES) {
  await switchLocale(code, nativeName)
  await scrollChatTop()
  await page.screenshot({ path: path.join(RAW, code, 'db-genius-ai-intent-recognition.png') })
  console.log('intent shot:', code)
}

// ---------- 3) 打开历史会话截「AI SQL 查询」 ----------
await page.goto(`${BASE}/admin/conversations`, { waitUntil: 'networkidle' })
await page.waitForTimeout(2000)
await hideBanner()
const oldRow = page.locator('tr', { hasText: QUERY }).filter({ hasText: OLD_CONV_DATE }).first()
await oldRow.locator('.arco-btn').nth(1).click()
await page.waitForURL('**/admin/chat**', { timeout: 15000 })
await page.waitForTimeout(2500)
await hideBanner()
const hasSql = await page.evaluate(() => document.body.innerText.includes('SELECT'))
console.log('old conversation opened, contains SELECT:', hasSql)

for (const [code, nativeName] of LOCALES) {
  await switchLocale(code, nativeName)
  // 优先锚定「执行 SQL」，让结果表在上方、SQL 语句在视口下部
  const anchored = (await scrollChatToText('执行 SQL', 620)) || (await scrollChatToText('SELECT', 620))
  if (!anchored) await scrollChatTop()
  await page.screenshot({ path: path.join(RAW, code, 'db-genius-ai-sql-query.png') })
  console.log('sql shot:', code, 'anchored:', anchored)
}

// ---------- 4) 逐语言截「数据库配置」 ----------
for (const [code, nativeName] of LOCALES) {
  await switchLocale(code, nativeName)
  await page.goto(`${BASE}/admin/db-config`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(2000)
  await hideBanner()
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(RAW, code, 'db-genius-database-config.png') })
  console.log('config shot:', code)
}

await browser.close()
console.log('ALL DONE')
