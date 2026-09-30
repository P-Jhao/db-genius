import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { once } from 'node:events'
import { existsSync, writeFileSync, unlinkSync } from 'node:fs'
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
      if ((await fetch(url)).ok) return
    } catch {
      // The test server is starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error('Vite did not start within 10 seconds')
}

test('context compaction displays seven locales and preserves compressed history', async () => {
  const url = `http://127.0.0.1:${await freePort()}`
  const configPath = fileURLToPath(new URL('../.s09-test-vite.config.mjs', import.meta.url))
  // A snapshot below .git needs an explicit frontend-only allowlist; sensitive files remain denied.
  writeFileSync(configPath, `import config from './vite.config.ts';
export default { ...config, server: { ...config.server, fs: { strict: true,
  allow: [${JSON.stringify(frontendDir)}],
  deny: ['.env', '.env.*', '*.{crt,pem,key,p12,pfx,cer,der}', '.npmrc', '.yarnrc.yml']
} } };`)
  const vite = spawn(process.execPath, [viteBin, '--config', configPath, '--host', '127.0.0.1', '--port', url.split(':').at(-1), '--strictPort'], {
    cwd: frontendDir, stdio: 'ignore', env: { ...process.env, VITE_API_BASE_URL: '/api' },
  })
  let browser
  try {
    await waitForVite(url, vite)
    browser = await chromium.launch(existsSync(chromium.executablePath())
      ? { headless: true } : { channel: 'chrome', headless: true })
    const page = await browser.newPage()
    let posts = 0
    await page.route('**/api/**', async (route) => {
      const path = new URL(route.request().url()).pathname
      if (!path.startsWith('/api/')) {
        await route.continue()
        return
      }
      let data
      if (path === '/api/chat') {
        posts += 1
        const content = { phase: 'start', tier: 'elide', message: 'Removing old observations',
          beforeTokens: 1800, affectedUnits: 2 }
        const events = [
          { type: 'conversation', content: 34 }, { type: 'context_compact', content },
          { type: 'context_compact', content: { ...content, phase: 'end', tier: 'summarize', afterTokens: 760 } },
          { type: 'content', content: 'Complete' }, { type: 'done', content: null },
        ].map((event) => ({ ...event, taskId: 'compact', step: 0, timestamp: 1790000005000 }))
        await route.fulfill({ contentType: 'text/event-stream',
          body: events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('') })
        return
      }
      if (path === '/api/trial/status') data = { trialEnabled: false }
      else if (path === '/api/model-config/active') data = { contextWindow: null }
      else if (path === '/api/db-config') data = []
      else if (path === '/api/chat/conversations') data = [{ id: 34, title: 'Compacted history',
        type: 'simple_chat', dbConfigIds: '', createdAt: '2026-09-29T10:03:00' }]
      else if (path === '/api/chat/conversations/34/messages') data = [
        { role: 'user', type: 'user', content: 'Remember', step: -1 },
        { role: 'assistant', type: 'compressed', content: 'Original answer remains', step: 1 },
        { role: 'assistant', type: 'summary', content: 'Compact summary', step: -2 },
      ].map((message, index) => ({ ...message, id: index + 1, conversationId: 34,
        fileUrl: null, createdAt: '2026-09-29T10:03:00' }))
      else throw new Error(`Unexpected endpoint ${path}`)
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ code: 200, message: 'success', data }) })
    })
    await page.addInitScript(() => {
      localStorage.setItem('token', 'fixture')
      localStorage.setItem('userInfo', JSON.stringify({ username: 'fixture', nickname: 'Fixture', role: 'user' }))
    })
    await page.goto(`${url}/admin/chat`)
    await page.locator('.chat-input-area textarea').fill('Compact context')
    await page.locator('.input-actions button.arco-btn-primary').click()
    await page.waitForFunction(() => document.querySelectorAll('.context-compact-details').length === 2)
    const localized = await page.evaluate(async () => {
      const [{ i18n }, { nextTick }] = await Promise.all([
        import('/src/i18n/index.ts'), import('/node_modules/.vite/deps/vue.js'),
      ])
      const result = {}
      for (const locale of ['en', 'zh-CN', 'zh-TW', 'ja', 'ms', 'es', 'fr']) {
        i18n.global.locale.value = locale
        await nextTick()
        const card = document.querySelector('.context_compact')
        if (!card) throw new Error('Missing compaction card')
        result[locale] = card.querySelector('.step-label')?.textContent?.trim()
      }
      i18n.global.locale.value = 'en'
      await nextTick()
      return result
    })
    assert.deepEqual(localized, { en: 'Context compaction', 'zh-CN': '上下文压缩', 'zh-TW': '上下文壓縮',
      ja: 'コンテキスト圧縮', ms: 'Pemadatan konteks', es: 'Compactación del contexto', fr: 'Compression du contexte' })
    const cards = page.locator('.context-compact-details')
    assert.deepEqual(await cards.nth(0).locator('dd').allTextContents(), ['Start', 'Elide', 'Removing old observations', '1800', '2'])
    assert.deepEqual(await cards.nth(1).locator('dd').allTextContents(), ['Complete', 'Summarize', 'Removing old observations', '1800', '760', '2'])
    assert.doesNotMatch((await cards.allTextContents()).join(''), /\[object Object\]/)
    const errors = await page.evaluate(async () => {
      const [{ createApp }, component, { i18n }] = await Promise.all([
        import('/node_modules/.vite/deps/vue.js'), import('/src/components/chat/SseStepCard.vue'), import('/src/i18n/index.ts'),
      ])
      const errors = []
      const app = createApp(component.default, { event: { taskId: 'invalid', step: 0, type: 'context_compact',
        content: { phase: 'unknown', tier: 'elide', message: 'Invalid' }, timestamp: 1790000005000 } })
      app.use(i18n)
      app.config.errorHandler = (error) => errors.push(error.message)
      app.mount(document.createElement('div'))
      app.unmount()
      return errors
    })
    assert.ok(errors.includes('Invalid context_compact SSE content'))
    await page.goto(`${url}/admin/conversations`)
    await page.locator('tr').filter({ hasText: 'Compacted history' }).locator('button:has(.arco-icon-message)').click()
    await page.waitForURL('**/admin/chat')
    await page.locator('.step-card.content').getByText('Original answer remains', { exact: true }).waitFor()
    await page.locator('.summary-card').getByText('Compact summary', { exact: true }).waitFor()
    assert.equal(posts, 1, 'history replay never repeats a chat POST')
    assert.equal(await page.locator('.streaming-indicator').count(), 0)
  } finally {
    await browser?.close()
    vite.kill()
    if (vite.exitCode === null) await once(vite, 'exit')
    unlinkSync(configPath)
  }
})
