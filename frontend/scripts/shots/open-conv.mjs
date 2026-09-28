// 打开指定历史会话，截图并 dump 内容结构
import { chromium } from 'playwright'

const BASE = 'http://localhost:5173'
const TITLE = process.argv[2] || '查询博客数据库里所有文章的标题和发布时间，按时间倒序排列'

const browser = await chromium.launch()
const ctx = await browser.newContext({
  storageState: '/tmp/dbgenius-dev/state.json',
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
  locale: 'zh-CN',
})
await ctx.addInitScript(() => localStorage.setItem('app-locale', 'zh-CN'))
const page = await ctx.newPage()

await page.goto(`${BASE}/admin/conversations`, { waitUntil: 'networkidle' })
await page.waitForTimeout(2000)
console.log('url now:', page.url())
const row = page.locator('tr', { hasText: TITLE }).first()
await row.locator('.arco-btn').nth(1).click()
await page.waitForURL('**/admin/chat**', { timeout: 15000 })
await page.waitForTimeout(3000)
await page.screenshot({ path: '/tmp/dbgenius-dev/chat-conv.png', fullPage: false })

// dump 消息结构
const info = await page.evaluate(() => {
  const bubbles = [...document.querySelectorAll('.message-bubble')].map((b) => ({
    role: b.className.includes('user') ? 'user' : 'assistant',
    text: (b.innerText || '').slice(0, 500),
  }))
  return bubbles
})
console.log(JSON.stringify(info, null, 2).slice(0, 4000))
await browser.close()
console.log('done')
