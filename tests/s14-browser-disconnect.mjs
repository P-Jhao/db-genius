import { chromium } from '../frontend/node_modules/playwright/index.mjs'
import { existsSync } from 'node:fs'

let input = ''
for await (const chunk of process.stdin) input += chunk
const request = JSON.parse(input)
const configuredPath = process.env.SQLCHAT_TEST_BROWSER_EXECUTABLE_PATH
if (configuredPath && !existsSync(configuredPath)) throw new Error('Configured browser executable does not exist')
const browserOptions = configuredPath
  ? { executablePath: configuredPath }
  : existsSync(chromium.executablePath())
    ? { executablePath: chromium.executablePath() }
    : { channel: 'chrome' }
const browser = await chromium.launch({ headless: true, ...browserOptions })
try {
  const page = await browser.newPage()
  await page.goto(request.url)
  const report = await page.evaluate(async ({ url, token, body }) => {
    const controller = new AbortController()
    const response = await fetch(`${url}/api/chat`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    if (response.status !== 200 || !response.body) throw new Error(`Chat HTTP ${response.status}`)
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let pending = ''
    let conversationId = null
    for (;;) {
      const { value, done } = await reader.read()
      if (done) throw new Error('Stream ended before first content')
      pending += decoder.decode(value, { stream: true })
      const packets = pending.split('\n\n')
      pending = packets.pop()
      for (const packet of packets) {
        const line = packet.split('\n').find((entry) => entry.startsWith('data:'))
        if (!line) continue
        const event = JSON.parse(line.slice(5))
        if (event.type === 'conversation') conversationId = event.content
        if (event.type === 'error') throw new Error('SSE error received')
        if (event.type !== 'content') continue
        const started = performance.now()
        const health = await fetch(`${url}/api/health/live`)
        const concurrentSeconds = (performance.now() - started) / 1000
        controller.abort()
        await reader.cancel().catch(() => {})
        return { conversationId, firstContent: event.content, healthStatus: health.status, concurrentSeconds }
      }
    }
  }, request)
  process.stdout.write(JSON.stringify(report))
} finally {
  await browser.close()
}
