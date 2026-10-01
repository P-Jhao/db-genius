import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { once } from 'node:events'
import { existsSync, readFileSync } from 'node:fs'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { chromium } from 'playwright'

const frontendDir = fileURLToPath(new URL('..', import.meta.url))
const viteBin = fileURLToPath(new URL('../node_modules/vite/bin/vite.js', import.meta.url))
const viteConfig = fileURLToPath(new URL('./fixtures/sse-test-vite.config.mjs', import.meta.url))

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

async function waitForDependencyOptimizer(cacheDir, viteOutput) {
  const metadataPath = join(cacheDir, 'deps', '_metadata.json')
  const requiredDependencies = [
    '@arco-design/web-vue',
    '@arco-design/web-vue/es/alert/style/css.js',
    '@arco-design/web-vue/es/avatar/style/css.js',
    '@arco-design/web-vue/es/button/style/css.js',
    '@arco-design/web-vue/es/divider/style/css.js',
    '@arco-design/web-vue/es/drawer/style/css.js',
    '@arco-design/web-vue/es/dropdown/style/css.js',
    '@arco-design/web-vue/es/icon',
    '@arco-design/web-vue/es/layout/style/css.js',
    '@arco-design/web-vue/es/menu/style/css.js',
    '@arco-design/web-vue/es/progress/style/css.js',
    '@arco-design/web-vue/es/select/style/css.js',
    '@arco-design/web-vue/es/spin/style/css.js',
    '@arco-design/web-vue/es/tag/style/css.js',
    '@arco-design/web-vue/es/textarea/style/css.js',
    '@arco-design/web-vue/es/tooltip/style/css.js',
    '@microsoft/fetch-event-source', 'pinia', 'vue', 'vue-i18n', 'vue-router',
  ]
  const deadline = Date.now() + 15000
  while (Date.now() < deadline) {
    try {
      const metadata = JSON.parse(readFileSync(metadataPath, 'utf8'))
      if (requiredDependencies.every((name) => Object.hasOwn(metadata.optimized, name))) return
    } catch (error) {
      if (!(error instanceof SyntaxError) && error.code !== 'ENOENT') throw error
    }
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
  throw new Error(`Vite dependency optimizer did not finish; cache=${metadataPath}; vite=${viteOutput()}`)
}

test('normal SSE EOF ends streaming and does not retry the chat POST', async () => {
  const port = await freePort()
  const url = `http://127.0.0.1:${port}`
  const viteCacheDir = join(tmpdir(), 'sqlchat-sse-eof-vite-cache', randomUUID())
  const vite = spawn(process.execPath, [viteBin, '--config', viteConfig, '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
    cwd: frontendDir,
    env: {
      ...process.env,
      SQLCHAT_TEST_VITE_CACHE_DIR: viteCacheDir,
      VITE_API_BASE_URL: `${url}/api`,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  let browser
  let releaseDelayedRoute
  let viteOutput = ''
  vite.stdout.setEncoding('utf8').on('data', (chunk) => { viteOutput += chunk })
  vite.stderr.setEncoding('utf8').on('data', (chunk) => { viteOutput += chunk })

  try {
    await waitForVite(url, vite)
    browser = await chromium.launch(existsSync(chromium.executablePath())
      ? { headless: true }
      : { channel: 'chrome', headless: true })
    const page = await browser.newPage()
    const mainFrameNavigations = []
    page.on('framenavigated', (frame) => {
      if (frame === page.mainFrame()) mainFrameNavigations.push(frame.url())
    })
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
    await page.route('**/api/trial/status', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ code: 200, message: 'success', data: { trialEnabled: false } }),
    }))

    await page.addInitScript(() => {
      localStorage.setItem('app-locale', 'en')
      localStorage.setItem('token', 'sse-eof-test-token')
      localStorage.setItem('userInfo', JSON.stringify({
        token: 'sse-eof-test-token', username: 'sse-eof-test', nickname: 'SSE EOF Test', role: 'user',
      }))
    })
    await page.route('**/api/db-config', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ code: 200, message: 'success', data: [] }),
    }))
    await page.route('**/api/model-config/active', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ code: 200, message: 'success', data: { contextWindow: null } }),
    }))
    await page.goto(`${url}/admin/chat`)
    await page.locator('.chat-page').waitFor({ timeout: 15000 })
    await page.evaluate(async () => {
      await Promise.all([
        import('/src/composables/useSse.ts'),
        import('/src/stores/chat.ts'),
      ])
    })
    await waitForDependencyOptimizer(viteCacheDir, () => viteOutput)
    await page.goto(`${url}/admin/chat`)
    await page.locator('.chat-page').waitFor({ timeout: 15000 })
    await page.evaluate(async () => {
      const { useSse } = await import('/src/composables/useSse.ts')
      const { useChatStore } = await import('/src/stores/chat.ts')
      const store = useChatStore()
      store.clearChat()
      const stream = useSse()
      window.sseEofTest = { store, stream }
      stream.send({ message: 'first question' })
    })
    const stableNavigationCount = mainFrameNavigations.length
    await page.waitForFunction(() => {
      const { store } = window.sseEofTest
      return store.messages.length === 1 && store.messages[0].content === 'answer-1' &&
        !store.messages[0].streaming && !store.isStreaming
    })
    assert.equal(chatPosts, 1)

    await page.waitForTimeout(1300)
    assert.equal(chatPosts, 1, 'normal EOF must not replay a write-capable POST')
    assert.equal(await page.evaluate(() => Boolean(window.sseEofTest?.stream)), true,
      `EOF must not reload the page and discard its test state; navigations=${JSON.stringify(mainFrameNavigations)}; vite=${viteOutput}`)
    assert.equal(mainFrameNavigations.length, stableNavigationCount,
      `EOF must not trigger a main-frame reload; navigations=${JSON.stringify(mainFrameNavigations)}; vite=${viteOutput}`)

    try {
      await page.evaluate(() => window.sseEofTest.stream.send({ message: 'second question' }))
    } catch (error) {
      throw new Error(`Second EOF scenario could not access its page state; navigations=${JSON.stringify(mainFrameNavigations)}; vite=${viteOutput}; ${String(error)}`)
    }
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
