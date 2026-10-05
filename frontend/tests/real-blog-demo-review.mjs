// In-memory login input from the operator smoke script; never persist token or credentials.
import { mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import { chromium } from 'playwright'
import { existsSync } from 'node:fs'

let input = ''
for await (const chunk of process.stdin) input += chunk
const { base, login, directory, conversationIds } = JSON.parse(input)
const browser = await chromium.launch(existsSync(chromium.executablePath())
  ? { headless: true } : { channel: 'chrome', headless: true })
let stage = 'launch'
let page
const diagnostics = {}
try {
  await mkdir(directory, { recursive: true })
  page = await browser.newPage({ viewport: { width: 1440, height: 1080 } })
  await page.addInitScript((user) => {
    localStorage.setItem('app-locale', 'zh-CN')
    localStorage.setItem('token', user.token)
    localStorage.setItem('userInfo', JSON.stringify(user))
  }, login)
  stage = 'chat-placeholder'
  await page.goto(`${base}/admin/chat`)
  await page.locator('.chat-page').waitFor()
  await page.getByPlaceholder('输入您的需求，例如：查看各表字段、统计各分类的已发布文章数量，或查询浏览量最高的文章…').waitFor()
  await page.screenshot({ path: join(directory, 'trial-placeholder.png'), fullPage: true })
  stage = 'conversations-table'
  const listResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname === '/api/chat/conversations')
  await page.goto(`${base}/admin/conversations`)
  const listEnvelope = await (await listResponse).json()
  if (listEnvelope.code !== 200) throw new Error('Conversations API failed')
  await page.locator('tr.arco-table-tr-empty').waitFor({ state: 'hidden' })
  let currentPage = 0
  let chatPosts = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/chat') chatPosts += 1
  })
  for (let index = 0; index < conversationIds.length; index += 1) {
    stage = `history-${index + 1}-exact-row`
    const recordIndex = listEnvelope.data.findIndex((record) => record.id === conversationIds[index])
    if (recordIndex < 0) throw new Error('Exact conversation ID absent')
    const targetPage = Math.floor(recordIndex / 20)
    while (currentPage !== targetPage) {
      await page.locator(currentPage < targetPage ? '.arco-pagination-item-next' : '.arco-pagination-item-prev').click()
      currentPage += currentPage < targetPage ? 1 : -1
    }
    // Arco row-key is a Vue key, not a rendered data-row-key attribute.
    // Resolve the exact API id to its rendered page/order, then verify its title.
    const row = page.locator('tbody tr.arco-table-tr').nth(recordIndex % 20)
    await row.locator('.arco-link').filter({ hasText: listEnvelope.data[recordIndex].title }).waitFor()
    stage = `history-${index + 1}-response-setup`
    const messagesResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname === `/api/chat/conversations/${conversationIds[index]}/messages`)
    await row.waitFor()
    stage = `history-${index + 1}-eye-button`
    diagnostics.buttons = await row.getByRole('button').count()
    await row.locator('button:has(.arco-icon-eye)').click()
    stage = `history-${index + 1}-messages-response`
    const historyResponse = await messagesResponse
    if (!historyResponse.ok()) throw new Error('History request failed')
    const envelope = await historyResponse.json()
    diagnostics.apiCode = envelope.code
    if (envelope.code !== 200) throw new Error('History response failed')
    const final = envelope.data.find((message) => message.type === 'summary')
    if (!final) throw new Error('History summary absent')
    stage = `history-${index + 1}-drawer-visible`
    diagnostics.drawerClasses = await page.locator('[class*=drawer]').evaluateAll((items) => items.map((item) => item.className))
    await page.locator('.arco-drawer-container:not(.mobile-drawer) .arco-drawer-body').waitFor()
    stage = `history-${index + 1}-summary-visible`
    await page.locator('.arco-drawer-container:not(.mobile-drawer) .message-content pre').filter({ hasText: final.content }).waitFor()
    await page.screenshot({ path: join(directory, `history-${index + 1}.png`), fullPage: true })
    stage = `history-${index + 1}-close-drawer`
    await page.locator('.arco-drawer-container:not(.mobile-drawer) .arco-drawer-close-btn').click()
    await page.locator('.arco-drawer-container:not(.mobile-drawer) .arco-drawer-body').waitFor({ state: 'hidden' })
    if (index === 0) {
      stage = 'chat-replay-first-conversation'
      await row.locator('button:has(.arco-icon-message)').click()
      await page.waitForURL('**/admin/chat')
      await page.locator('.summary-card table').nth(9).waitFor()
      if (await page.locator('.summary-card table').count() !== 10) throw new Error('Expected ten schema tables')
      await page.locator('.reasoning-card').first().waitFor()
      await page.getByText('ai_conversation', { exact: false }).first().waitFor()
      await page.locator('.summary-card').scrollIntoViewIfNeeded()
      await page.locator('.summary-card').screenshot({ path: join(directory, 'chat-replay-11.png'), animations: 'disabled' })
      if (chatPosts !== 0) throw new Error('History review must not submit chat')
      const reloadResponse = page.waitForResponse((response) =>
        new URL(response.url()).pathname === '/api/chat/conversations')
      await page.goto(`${base}/admin/conversations`)
      await reloadResponse
      await page.locator('tr.arco-table-tr-empty').waitFor({ state: 'hidden' })
      currentPage = 0
    }
  }
} catch (error) {
  if (page) await page.screenshot({ path: join(directory, 'failure.png'), fullPage: true })
  process.stderr.write(JSON.stringify({ stage, errorName: error.name, ...diagnostics }))
  process.exitCode = 1
} finally {
  await browser.close()
}
