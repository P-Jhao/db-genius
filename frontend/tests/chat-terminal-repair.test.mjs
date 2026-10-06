import assert from 'node:assert/strict'
import { test } from 'node:test'
import { launchBrowser, startFrontend, stopFrontend, success } from './fixtures/chat-terminal-browser.mjs'

const errorText = 'SQL 查询需要至少选择一个数据库配置'
const question = '查看 posts 表有哪些字段'
const reasoning = '读取 MySQL 元数据后，按字段名整理结果。'
const report = '## posts 表字段\n\n| 字段 | 类型 |\n| --- | --- |\n| id | bigint |\n| title | varchar(255) |\n\n共 2 个字段。'
const clarify = { question: '请选择任务类型', reasoning: '请确认查询目标',
  options: [{ intent: 'sql_query', label: '确认 SQL 查询' }] }
const event = (type, content, step = 1) => ({ taskId: 'terminal-fixture', step, type, content, timestamp: Date.now() })
const frame = (events) => events.map((value) => `data: ${JSON.stringify(value)}\n\n`).join('')
const createdAt = '2026-10-06T10:00:00'
const conversation = { id: 91, title: '终态回归', type: 'sql_query', dbConfigIds: '[]', createdAt }
const history = (rows) => rows.map(([role, type, content], index) => ({
  id: index + 1, conversationId: 91, role, type, content, step: index,
  reasoningContent: null, toolCalls: null, fileUrl: null, createdAt,
}))

test('mock SSE: clarify confirmation without DB renders terminal error and refresh replays it', async () => {
  await withPage(async ({ page, url, requests, setHistory }) => {
    await page.route('**/api/chat', async (route) => {
      const body = route.request().postDataJSON()
      requests.push(body)
      const events = requests.length === 1
        ? [event('conversation', 91), event('clarify', clarify)]
        : [event('conversation', 91), event('error', errorText)]
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: frame(events) })
    })
    await page.goto(`${url}/admin/chat`)
    await page.locator('textarea').fill(question)
    await page.locator('.input-actions button.arco-btn-primary').click()
    await page.locator('.clarify-card').waitFor()
    await page.getByRole('button', { name: '确认 SQL 查询', exact: true }).click()
    const error = page.locator('.step-card.error')
    await error.waitFor()
    assert.equal((await error.locator('pre').textContent()).trim(), errorText)
    assert.equal(await error.evaluate((node) => getComputedStyle(node).backgroundColor), 'rgb(255, 242, 240)')
    assert.equal(await page.locator('.clarify-card').count(), 1, 'confirmation must not render a second clarify card')
    assert.equal(requests.length, 2)
    assert.equal(requests[1].confirmedIntent, 'sql_query')
    assert.equal(requests[1].conversationId, 91)
    assert.equal(requests[1].dbConfigIds, null)
    assert.equal(requests[1].message, question)
    await assertInputReady(page)
    setHistory(history([['user', 'user', question], ['assistant', 'clarify', JSON.stringify(clarify)],
      ['assistant', 'error', errorText]]))
    await reopenHistory(page, url)
    assert.equal((await page.locator('.step-card.error pre').textContent()).trim(), errorText)
    assert.equal(await page.locator('.clarify-card').count(), 1)
    assert.equal(requests.length, 2, 'history GET must not replay chat POST')
    await assertInputReady(page)
  })
})

test('mock SSE: metadata report finalizes once, preserves reasoning/table and history content', async () => {
  await withPage(async ({ page, url, requests, setHistory }) => {
    await page.route('**/api/chat', async (route) => {
      requests.push(route.request().postDataJSON())
      const midpoint = Math.floor(report.length / 2)
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: frame([
        event('conversation', 91), event('reasoning', reasoning),
        event('summary_delta', report.slice(0, midpoint), 2),
        event('summary_delta', report.slice(midpoint), 2), event('summary', report, 2),
        event('summary_delta', '不应出现的晚到增量', 2), event('done', '', 2),
      ]) })
    })
    await page.goto(`${url}/admin/chat`)
    await page.locator('textarea').fill(question)
    await page.locator('.input-actions button.arco-btn-primary').click()
    await page.locator('.summary-card table').waitFor()
    await assertReport(page)
    const content = await page.evaluate(async () => {
      const { useChatStore } = await import('/src/stores/chat.ts')
      const store = useChatStore()
      return { content: store.messages.at(-1).content, isStreaming: store.isStreaming }
    })
    assert.deepEqual(content, { content: report, isStreaming: false })
    await assertInputReady(page)
    setHistory(history([['user', 'user', question], ['assistant', 'reasoning', reasoning],
      ['assistant', 'summary', report], ['assistant', 'done', '']]))
    await reopenHistory(page, url)
    await assertReport(page)
    assert.equal(requests.length, 1)
  })
})

async function assertInputReady(page) {
  const input = page.locator('textarea')
  await page.waitForFunction(() => !document.querySelector('textarea').disabled)
  await input.fill('下一条消息')
  assert.equal(await page.locator('.input-actions button.arco-btn-primary').isEnabled(), true)
  assert.equal(await page.locator('.streaming-indicator').count(), 0)
}

async function assertReport(page) {
  assert.equal(await page.locator('.summary-card').count(), 1)
  const summary = page.locator('.summary-card')
  assert.equal(await summary.locator('table').count(), 1)
  assert.equal(await summary.locator('tbody tr').count(), 2)
  assert.match(await summary.textContent(), /id.*bigint.*title.*varchar\(255\).*共 2 个字段/s)
  assert.doesNotMatch(await summary.textContent(), /不应出现的晚到增量/)
  const reason = page.locator('.reasoning-card')
  assert.equal(await reason.count(), 1)
  assert.equal(await reason.locator('.reasoning-content').isVisible(), false)
  await reason.locator('.reasoning-header').click()
  assert.equal(await reason.locator('.reasoning-content').isVisible(), true)
  assert.equal((await reason.locator('pre').textContent()).trim(), reasoning)
}

async function reopenHistory(page, url) {
  await page.goto(`${url}/admin/conversations`)
  await page.reload()
  const row = page.locator('tr').filter({ hasText: conversation.title })
  await row.waitFor()
  await row.locator('button:has(.arco-icon-message)').click()
  await page.waitForURL('**/admin/chat')
  await page.locator('.message-bubble.assistant').waitFor()
}

async function withPage(run) {
  const { url, vite } = await startFrontend()
  let browser
  try {
    browser = await launchBrowser()
    const page = await browser.newPage()
    const requests = []
    const pageErrors = []
    let messages = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await page.addInitScript(() => {
      localStorage.setItem('app-locale', 'zh-CN')
      localStorage.setItem('token', 'terminal-test-token')
      localStorage.setItem('userInfo', JSON.stringify({ token: 'terminal-test-token',
        username: 'terminal-test', nickname: 'Terminal Test', role: 'user' }))
    })
    await page.route((requestUrl) => requestUrl.pathname.startsWith('/api/'), async (route) => {
      const path = new URL(route.request().url()).pathname
      let data
      if (path === '/api/trial/status') data = { trialEnabled: false }
      else if (path === '/api/db-config') data = []
      else if (path === '/api/model-config/active') data = { contextWindow: null }
      else if (path === '/api/chat/conversations') data = [conversation]
      else if (path === '/api/chat/conversations/91/messages') data = messages
      else throw new Error(`Unexpected fixture API: ${path}`)
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success(data)) })
    })
    await run({ page, url, requests, setHistory: (rows) => { messages = rows } })
    assert.deepEqual(pageErrors, [], 'real Vue page must not raise runtime errors')
  } finally { await stopFrontend(vite, browser) }
}
