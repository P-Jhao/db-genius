import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { createServer } from 'node:net'
import { existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
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
      if ((await fetch(url)).ok) return
    } catch {
      // Vite is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error('Vite did not start within 10 seconds')
}

function waitForSignal(promise, label, timeout = 15000) {
  let timer
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`Timed out waiting for ${label}`)), timeout)
    }),
  ]).finally(() => clearTimeout(timer))
}

async function stopProcess(process) {
  if (process.exitCode !== null) return
  const exited = once(process, 'exit')
  process.kill()
  await Promise.race([exited, new Promise((resolve) => setTimeout(resolve, 5000))])
  if (process.exitCode === null) process.kill('SIGKILL')
}

test('Stop clears reactive streaming state immediately and retains the partial answer', { timeout: 90000 }, async () => {
  const port = await freePort()
  const url = `http://127.0.0.1:${port}`
  const vite = spawn(process.execPath, [viteBin, '--config', viteConfig, '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
    cwd: frontendDir,
    env: {
      ...process.env,
      SQLCHAT_TEST_VITE_CACHE_DIR: join(tmpdir(), 'sqlchat-sse-stop-vite-cache', randomUUID()),
      VITE_API_BASE_URL: `${url}/api`,
    },
    stdio: 'ignore',
  })
  let browser
  let page
  let releaseRoute
  let routeStartedResolve
  let routeFinishedResolve
  let routeHandlerStarted = false
  const routeStarted = new Promise((resolve) => { routeStartedResolve = resolve })
  const routeFinished = new Promise((resolve) => { routeFinishedResolve = resolve })

  try {
    await waitForVite(url, vite)
    browser = await chromium.launch(existsSync(chromium.executablePath())
      ? { headless: true }
      : { channel: 'chrome', headless: true })
    page = await browser.newPage()
    await page.route('**/api/chat', async (route) => {
      routeHandlerStarted = true
      routeStartedResolve()
      await new Promise((resolve) => { releaseRoute = resolve })
      try {
        await route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
      } catch (error) {
        if (route.request().failure()?.errorText !== 'net::ERR_ABORTED') throw error
      } finally {
        routeFinishedResolve()
      }
    })

    let chatPost
    const requestStarted = new Promise((resolve) => {
      page.on('request', (request) => {
        const requestUrl = new URL(request.url())
        if (requestUrl.pathname === '/api/chat' && request.method() === 'POST') {
          chatPost = request
          resolve(request)
        }
      })
    })

    await page.goto(url)
    await page.evaluate(async () => {
      const { useSse } = await import('/src/composables/useSse.ts')
      const { useChatStore } = await import('/src/stores/chat.ts')
      const store = useChatStore()
      store.clearChat()
      const stream = useSse()
      window.sseStopTest = { store, stream }
      stream.send({ message: 'stop after partial answer' })
    })
    await Promise.all([
      waitForSignal(routeStarted, 'API fixture route'),
      waitForSignal(requestStarted, 'chat POST'),
    ])
    assert.ok(chatPost, 'the Stop scenario must start exactly one chat POST')
    const requestFailure = page.waitForEvent('requestfailed', {
      predicate: (request) => request === chatPost,
      timeout: 5000,
    })
    requestFailure.catch(() => {})

    let stopState
    try {
      stopState = await page.evaluate(async () => {
      const { store, stream } = window.sseStopTest
      const assistantMessage = store.messages.at(-1)
      if (!assistantMessage || assistantMessage.role !== 'assistant') {
        throw new Error('The active assistant message was not added to the store')
      }
      const { watchAssistantStreaming } = await import('/tests/fixtures/sse-stop-test-helper.mjs')
      let reactiveStopObserved = false
      const stopWatching = watchAssistantStreaming(
        store,
        assistantMessage.id,
        (streaming) => {
          if (streaming === false) reactiveStopObserved = true
        },
      )
      store.handleSseEvent({
        taskId: 'stop-test-task', step: 1, type: 'content', content: 'Partial answer stays visible', timestamp: Date.now(),
      })
      stream.abort()
      stopWatching()
      return {
        reactiveStopObserved,
        isStreaming: store.isStreaming,
        messageStreaming: store.messages.find((message) => message.id === assistantMessage.id)?.streaming,
        content: store.messages.find((message) => message.id === assistantMessage.id)?.content,
      }
      })
    } catch (error) {
      releaseRoute?.()
      throw new Error(`Stop state probe failed: ${String(error)}`)
    }

    assert.deepEqual(stopState, {
      reactiveStopObserved: true,
      isStreaming: false,
      messageStreaming: false,
      content: 'Partial answer stays visible',
    })
    const failedRequest = await requestFailure
    assert.equal(failedRequest.failure()?.errorText, 'net::ERR_ABORTED',
      'Stop must abort the exact in-flight POST while releasing UI state immediately')
    releaseRoute?.()
    await waitForSignal(routeFinished, 'API fixture route shutdown', 5000)
  } finally {
    releaseRoute?.()
    if (routeHandlerStarted) {
      await waitForSignal(routeFinished, 'API fixture route cleanup', 5000)
    }
    await page?.close()
    await browser?.close()
    if (vite.exitCode === null) await stopProcess(vite)
  }
})
