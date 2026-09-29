import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { once } from 'node:events'
import { existsSync } from 'node:fs'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const frontendDir = fileURLToPath(new URL('..', import.meta.url))
const viteBin = fileURLToPath(new URL('../node_modules/vite/bin/vite.js', import.meta.url))

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

test('normal SSE EOF ends streaming and does not retry the chat POST', async () => {
  const port = await freePort()
  const url = `http://127.0.0.1:${port}`
  const vite = spawn(process.execPath, [viteBin, '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
    cwd: frontendDir,
    stdio: 'ignore',
  })
  let browser
  let releaseDelayedRoute

  try {
    await waitForVite(url, vite)
    browser = await chromium.launch(existsSync(chromium.executablePath())
      ? { headless: true }
      : { channel: 'chrome', headless: true })
    const page = await browser.newPage()
    let chatPosts = 0
    let delayedRouteStartedResolve
    const delayedRouteStarted = new Promise((resolve) => { delayedRouteStartedResolve = resolve })
    await page.route('**/api/chat', async (route) => {
      assert.equal(route.request().method(), 'POST')
      const requestNumber = ++chatPosts
      if (requestNumber === 3) {
        await route.fulfill({ status: 503, body: 'unavailable' })
        return
      }
      if (requestNumber === 4) {
        delayedRouteStartedResolve()
        await new Promise((resolve) => { releaseDelayedRoute = resolve })
      }
      try {
        await route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: `data: ${JSON.stringify({ taskId: `task-${requestNumber}`, step: 1, type: 'content', content: `answer-${requestNumber}`, timestamp: Date.now() })}\n\n`,
        })
      } catch (error) {
        if (requestNumber !== 4) throw error
      }
    })

    await page.goto(url)
    await page.evaluate(async () => {
      const { useSse } = await import('/src/composables/useSse.ts')
      const { useChatStore } = await import('/src/stores/chat.ts')
      const store = useChatStore()
      store.clearChat()
      const stream = useSse()
      window.sseEofTest = { store, stream }
      stream.send({ message: 'first question' })
    })
    await page.waitForFunction(() => {
      const { store } = window.sseEofTest
      return store.messages.length === 1 && store.messages[0].content === 'answer-1' &&
        !store.messages[0].streaming && !store.isStreaming
    })
    assert.equal(chatPosts, 1)

    await page.waitForTimeout(1300)
    assert.equal(chatPosts, 1, 'normal EOF must not replay a write-capable POST')

    await page.evaluate(() => window.sseEofTest.stream.send({ message: 'second question' }))
    await page.waitForFunction(() => {
      const { store } = window.sseEofTest
      return store.messages.length === 2 && store.messages[1].content === 'answer-2' &&
        store.messages.every((message) => !message.streaming) && !store.isStreaming
    })
    assert.equal(chatPosts, 2)

    await page.evaluate(() => window.sseEofTest.stream.send({ message: 'failing question' }))
    await page.waitForFunction(() => {
      const { store, stream } = window.sseEofTest
      return store.messages.length === 3 && !store.messages[2].streaming &&
        !store.isStreaming && stream.error.value !== null
    })
    await page.waitForTimeout(1300)
    assert.equal(chatPosts, 3, 'failed chat POST must not be retried')

    await page.evaluate(() => {
      const { store, stream } = window.sseEofTest
      store.addUserMessage('old question')
      stream.send({ message: 'old question' })
    })
    await delayedRouteStarted
    const oldMessageStopped = await page.evaluate(() => {
      const { store, stream } = window.sseEofTest
      store.addUserMessage('new question')
      stream.send({ message: 'new question' })
      return !store.messages[4].streaming
    })
    assert.equal(oldMessageStopped, true, 'replacing a stream must finish its assistant message')
    releaseDelayedRoute()
    await page.waitForFunction(() => {
      const { store } = window.sseEofTest
      return store.messages.length === 7 && store.messages[6].content === 'answer-5' &&
        !store.messages[4].streaming && !store.messages[6].streaming && !store.isStreaming
    })
    await page.waitForTimeout(200)
    const messages = await page.evaluate(() => window.sseEofTest.store.messages.map((message) => ({
      content: message.content,
      streaming: message.streaming,
    })))
    assert.equal(messages[4].content, '', 'delayed old response must not enter the new turn')
    assert.equal(messages[6].content, 'answer-5')
    assert.equal(chatPosts, 5)
  } finally {
    releaseDelayedRoute?.()
    await browser?.close()
    vite.kill()
    if (vite.exitCode === null) await once(vite, 'exit')
  }
})
