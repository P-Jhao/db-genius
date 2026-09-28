// 探索脚本：登录并查看历史会话，dump 关键信息
import { chromium } from 'playwright'

const BASE = 'http://localhost:5173'

const browser = await chromium.launch()
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
  locale: 'zh-CN',
})
await ctx.addInitScript(() => {
  localStorage.setItem('app-locale', 'zh-CN')
})
const page = await ctx.newPage()

// 登录
await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1500)
const userVal = await page.locator('input').first().inputValue()
console.log('username prefilled:', JSON.stringify(userVal))
await page.getByRole('button', { name: /登 录|登录/ }).click()
await page.waitForURL('**/admin/**', { timeout: 20000 })
console.log('logged in, url:', page.url())
await page.waitForTimeout(3000)

// 会话列表
await page.goto(`${BASE}/admin/conversations`, { waitUntil: 'networkidle' })
await page.waitForTimeout(2500)
await page.screenshot({ path: '/tmp/dbgenius-dev/conversations.png' })
const text = await page.locator('body').innerText()
console.log('--- conversations page text (first 2000 chars) ---')
console.log(text.slice(0, 2000))

// 保存登录态
await ctx.storageState({ path: '/tmp/dbgenius-dev/state.json' })
await browser.close()
console.log('done')
