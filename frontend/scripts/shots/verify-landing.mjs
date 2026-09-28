// 验证落地页多语言截图接线
import { chromium } from 'playwright'

const BASE = 'http://localhost:5173'
const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await ctx.newPage()

for (const code of ['en', 'ja', 'zh-CN']) {
  const failed = []
  page.on('requestfailed', (r) => failed.push(r.url()))
  const notFound = []
  page.on('response', (r) => {
    if (r.status() === 404 && r.url().includes('/landing/')) notFound.push(r.url())
  })
  await page.goto(`${BASE}/?lang=${code}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
  const hero = await page.locator('.hero-visual img').first()
  const heroSrc = await hero.getAttribute('src')
  const heroOk = await hero.evaluate((el) => el.complete && el.naturalWidth > 0)

  // 切到 compare tab（第 3 个）
  await page.locator('.showcase-tabs .arco-tabs-tab').nth(2).click()
  await page.waitForTimeout(1200)
  const tab = await page.locator('.showcase-figure img')
  const tabSrc = await tab.getAttribute('src')
  const tabOk = await tab.evaluate((el) => el.complete && el.naturalWidth > 0)

  console.log(`${code}: hero=${heroSrc} loaded=${heroOk} | compareTab=${tabSrc} loaded=${tabOk}`)
  console.log(`  404s: ${notFound.length ? notFound.join(', ') : 'none'}; failed: ${failed.length ? failed.join(', ') : 'none'}`)
  page.removeAllListeners('requestfailed')
  page.removeAllListeners('response')
}

await page.screenshot({ path: '/tmp/dbgenius-dev/landing-en.png' })
await browser.close()
console.log('verify done')
