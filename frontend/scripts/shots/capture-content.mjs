// 素材捕获：zh-CN 跑一次实时 SQL 查询，连拍流式过程 + 完成后截图 + db-config 页
import { chromium } from 'playwright'
import fs from 'node:fs'

const BASE = 'http://localhost:5173'
const OUT = '/tmp/dbgenius-dev'
const QUERY = '查询博客数据库里所有文章的标题和发布时间，按时间倒序排列'

const HIDE_CSS = '.trial-banner{display:none!important}.app-root{--banner-height:0px!important}'

const browser = await chromium.launch()
const ctx = await browser.newContext({
  storageState: `${OUT}/state.json`,
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
  locale: 'zh-CN',
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

// 1) 打开 chat，新对话
await page.goto(`${BASE}/admin/chat`, { waitUntil: 'networkidle' })
await page.waitForTimeout(2000)
await page.addStyleTag({ content: HIDE_CSS })

// 2) 选数据库（打开下拉，选第一项）
await page.locator('.db-selector .arco-select-view').first().click()
await page.waitForTimeout(800)
await page.locator('.arco-select-dropdown .arco-select-option').first().click()
await page.waitForTimeout(500)

// 3) 输入并发送
await page.locator('textarea').fill(QUERY)
await page.getByRole('button', { name: /发 送|发送/ }).click()
console.log('sent, streaming...')

// 4) 流式连拍
let n = 0
const t0 = Date.now()
let sawSteps = 0
while (Date.now() - t0 < 90000) {
  const streaming = (await page.locator('button:has-text("停止")').count()) > 0
  const steps = await page.locator('.step-card').count()
  sawSteps = Math.max(sawSteps, steps)
  if (streaming || steps > 0) {
    n++
    await page.screenshot({ path: `${OUT}/stream-${String(n).padStart(2, '0')}.png` })
  }
  if (!streaming && Date.now() - t0 > 4000) break
  await page.waitForTimeout(700)
}
console.log('burst shots:', n, 'max step cards:', sawSteps)

// 5) 完成态截图（滚到消息底部看 SQL+结果）
await page.waitForTimeout(1500)
await page.evaluate(() => {
  const c = document.querySelector('.chat-messages')
  if (c) c.scrollTop = c.scrollHeight
})
await page.waitForTimeout(800)
await page.screenshot({ path: `${OUT}/final-bottom.png` })
await page.evaluate(() => {
  const c = document.querySelector('.chat-messages')
  if (c) c.scrollTop = 0
})
await page.waitForTimeout(800)
await page.screenshot({ path: `${OUT}/final-top.png` })

// 6) db-config 页
await page.goto(`${BASE}/admin/db-config`, { waitUntil: 'networkidle' })
await page.waitForTimeout(2500)
await page.addStyleTag({ content: HIDE_CSS })
await page.waitForTimeout(500)
await page.screenshot({ path: `${OUT}/db-config.png` })

fs.writeFileSync(`${OUT}/capture.log`, `shots=${n} steps=${sawSteps}\n`)
await browser.close()
console.log('done')
