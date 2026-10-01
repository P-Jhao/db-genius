import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { once } from 'node:events'
import { existsSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const frontendDir = fileURLToPath(new URL('..', import.meta.url))
const viteBin = fileURLToPath(new URL('../node_modules/vite/bin/vite.js', import.meta.url))
const viteConfig = fileURLToPath(new URL('./fixtures/sse-test-vite.config.mjs', import.meta.url))
const fixtures = JSON.parse(readFileSync(new URL('./fixtures/chat-contract.json', import.meta.url), 'utf8'))

async function freePort() {
  const server = createServer()
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  const address = server.address()
  if (typeof address !== 'object' || address === null) throw new Error('No test server port')
  server.close()
  await once(server, 'close')
  return address.port
}

async function waitForVite(url, process) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (process.exitCode !== null) throw new Error(`Vite exited with ${process.exitCode}`)
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {
      // Vite is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error('Vite did not start within 10 seconds')
}

test('Java chat branches are consumed over mocked browser SSE without replay', async () => {
  const port = await freePort()
  const url = `http://127.0.0.1:${port}`
  const vite = spawn(process.execPath, [viteBin, '--config', viteConfig, '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
    cwd: frontendDir,
    env: {
      ...process.env,
      SQLCHAT_TEST_VITE_CACHE_DIR: join(tmpdir(), 'sqlchat-chat-contract-vite-cache', randomUUID()),
      VITE_API_BASE_URL: `${url}/api`,
    },
    stdio: 'ignore',
  })
  let browser
  try {
    await waitForVite(url, vite)
    browser = await chromium.launch(existsSync(chromium.executablePath())
      ? { headless: true }
      : { channel: 'chrome', headless: true })
    const page = await browser.newPage()
    const posts = []
    const observedRequests = []
    page.on('request', (request) => observedRequests.push({ method: request.method(), url: request.url() }))
    await page.route('**/api/chat', async (route) => {
      const request = route.request()
      assert.equal(request.method(), 'POST')
      assert.match(request.headers()['accept-language'], /^[a-z]{2}/)
      const body = request.postDataJSON()
      posts.push(body)
      if (body.confirmedIntent === 'simple_chat') {
        await route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: [
            { taskId: 'confirmed-1', step: 0, type: 'conversation', content: 33, timestamp: 1790000002010 },
            { taskId: 'confirmed-1', step: 0, type: 'content', content: 'Confirmed answer', timestamp: 1790000002011 },
            { taskId: 'confirmed-1', step: -1, type: 'done', content: null, timestamp: 1790000002012 },
          ].map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''),
        })
        return
      }
      const fixture = Object.values(fixtures).find((entry) => entry.request.message === body.message)
      if (!fixture) throw new Error(`Unexpected chat request: ${body.message}`)
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: fixture.events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''),
      })
    })
    await page.route('**/api/chat/conversations/*/messages', async (route) => {
      const id = Number(route.request().url().match(/\/conversations\/(\d+)\/messages$/)?.[1])
      const fixture = [fixtures.simple, fixtures.sql, fixtures.clarify]
        .find((entry) => entry.history[0].conversationId === id)
      if (!fixture) throw new Error(`Unexpected history ID: ${id}`)
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        code: 200, message: 'success', data: fixture.history,
      }) })
    })
    await page.route('**/api/chat/conversations', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        code: 200, message: 'success', data: [{ id: 33, title: 'Show orders', type: 'sql_query',
          dbConfigIds: '', totalTokens: 10, contextTokens: 8, createdAt: '2026-09-29T10:02:00' }],
      }) })
    })
    await page.route('**/api/trial/status', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ code: 200, message: 'success', data: { trialEnabled: false } }),
    }))
    await page.route('**/api/db-config', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ code: 200, message: 'success', data: [] }),
    }))
    await page.route('**/api/model-config/active', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ code: 200, message: 'success', data: { contextWindow: null } }),
    }))
    await page.addInitScript(() => {
      localStorage.setItem('token', 'fixture-token')
      localStorage.setItem('userInfo', JSON.stringify({
        token: 'fixture-token', username: 'fixture', nickname: 'Fixture', role: 'user',
      }))
    })

    await page.goto(`${url}/admin/chat`)
    await page.locator('.chat-page').waitFor({ timeout: 15000 })
    await page.goto(`${url}/admin/conversations`)
    await page.locator('tr').filter({ hasText: 'Show orders' }).waitFor({ timeout: 15000 })
    await page.evaluate(async () => {
      await Promise.all([
        import('/src/composables/useSse.ts'),
        import('/src/views/admin/ConversationsPage.vue'),
      ])
    })
    await page.evaluate(async () => {
      const { useSse } = await import('/src/composables/useSse.ts')
      const { useChatStore } = await import('/src/stores/chat.ts')
      const { getMessages } = await import('/src/api/chat.ts')
      window.chatContract = { store: useChatStore(), stream: useSse(), getMessages }
    })

    for (const name of ['simple', 'sql', 'clarify', 'error', 'eof']) {
      const fixture = fixtures[name]
      await page.evaluate((request) => {
        const { store, stream } = window.chatContract
        store.clearChat()
        store.addUserMessage(request.message)
        stream.send(request)
      }, fixture.request)
      await page.waitForFunction((taskId) => {
        const { store } = window.chatContract
        return store.messages.length === 2 && store.currentTaskId === taskId &&
          !store.messages[1].streaming && !store.isStreaming
      }, fixture.events[0].taskId)
      const actual = await page.evaluate(() => {
        const { store, stream } = window.chatContract
        const message = store.messages[1]
        return {
          content: message.content,
          blocks: message.blocks.map((block) => block.kind === 'event'
            ? { kind: block.kind, type: block.event.type, content: block.event.content }
            : { kind: block.kind, text: block.text, done: block.done }),
          streaming: message.streaming,
          isStreaming: store.isStreaming,
          conversationId: store.currentConversationId,
          taskId: store.currentTaskId,
          usage: message.usage,
          error: stream.error.value,
        }
      })
      assert.equal(actual.streaming, false, `${name}: assistant must stop loading`)
      assert.equal(actual.isStreaming, false, `${name}: composer must stop loading`)
      assert.equal(actual.error, null, `${name}: valid SSE/EOF is not a transport failure`)
      assert.equal(actual.taskId, fixture.events[0].taskId)

      if (name === 'simple') {
        assert.equal(actual.conversationId, 31)
        assert.equal(actual.content, 'Hello there')
        assert.deepEqual(actual.blocks.filter((block) => block.kind === 'reasoning'), [
          { kind: 'reasoning', text: 'Think', done: true },
        ])
        assert.equal(actual.usage.totalTokens, 12)
      } else if (name === 'sql') {
        assert.equal(actual.conversationId, 32)
        assert.equal(actual.content, 'There are 3 orders.', 'final summary replaces differing deltas')
        assert.deepEqual(actual.blocks.filter((block) => block.kind === 'summary'), [
          { kind: 'summary', text: 'There are 3 orders.', done: true },
        ])
        assert.equal(actual.blocks.find((block) => block.type === 'step')?.content,
          'SELECT COUNT(*) FROM orders returned 3')
        assert.equal(actual.usage.totalTokens, 25)
      } else if (name === 'clarify') {
        assert.equal(actual.conversationId, null)
        assert.equal(actual.blocks.find((block) => block.type === 'clarify')?.content.question,
          'Choose an intent')
        assert.equal(actual.usage.totalTokens, 10, 'usage after clarify is retained')
      } else if (name === 'error') {
        assert.equal(actual.blocks.find((block) => block.type === 'error')?.content,
          'Model unavailable')
      } else {
        assert.equal(actual.content, 'Partial', 'EOF preserves received content')
      }
    }

    assert.equal(posts.length, 5, 'one POST per question; no automatic replay')
    assert.deepEqual(posts[1], fixtures.sql.request)
    await page.waitForTimeout(1300)
    assert.equal(posts.length, 5, 'EOF and error must not retry a write-capable POST')

    for (const name of ['simple', 'sql']) {
      const result = await page.evaluate(async (id) => {
        const { getMessages } = window.chatContract
        return (await getMessages(id)).data
      }, fixtures[name].history[0].conversationId)
      assert.deepEqual(result, fixtures[name].history, `${name}: camelCase history wrapper`)
      assert.equal(result.at(-1).content,
        name === 'simple' ? 'Hello there' : 'There are 3 orders.')
    }

    await page.goto(`${url}/admin/conversations`)
    const row = page.locator('tr').filter({ hasText: 'Show orders' })
    await row.locator('button:has(.arco-icon-message)').click()
    try {
      await page.waitForURL('**/admin/chat')
    } catch (error) {
      const pageState = await page.evaluate(() => ({
        url: window.location.href,
        body: document.body.innerText.slice(0, 1200),
        drawer: document.querySelector('.arco-drawer')?.textContent?.slice(0, 400) ?? null,
      }))
      throw new Error(`History continue did not navigate. state=${JSON.stringify(pageState)} requests=${JSON.stringify(observedRequests)} posts=${JSON.stringify(posts)} ${String(error)}`)
    }
    const card = page.locator('.clarify-card')
    await card.waitFor()
    assert.equal(await card.locator('.clarify-question').textContent(), 'Choose an intent')
    assert.deepEqual(await card.locator('button').allTextContents(), ['SQL query', 'Simple chat'])
    assert.equal(await page.locator('.streaming-indicator').count(), 0)
    await card.locator('button').nth(1).click()
    await page.waitForFunction(() => {
      const text = document.querySelector('.assistant-text')?.textContent
      return text?.includes('Confirmed answer')
    })
    assert.equal(posts.length, 6)
    assert.equal(posts[5].message, 'Show orders')
    assert.equal(posts[5].conversationId, 33)
    assert.equal(posts[5].confirmedIntent, 'simple_chat')
  } finally {
    await browser?.close()
    vite.kill()
    if (vite.exitCode === null) await once(vite, 'exit')
  }
})
