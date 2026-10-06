import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { mkdtemp, rm } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createServer } from 'node:net'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const frontendDir = fileURLToPath(new URL('..', import.meta.url))
const repoDir = fileURLToPath(new URL('../..', import.meta.url))
const viteBin = fileURLToPath(new URL('../node_modules/vite/bin/vite.js', import.meta.url))
const pythonBin = join(repoDir, 'backend', '.venv', process.platform === 'win32' ? 'Scripts' : 'bin',
  process.platform === 'win32' ? 'python.exe' : 'python')
const apiFixture = fileURLToPath(new URL('./fixtures/s07_api.py', import.meta.url))

async function freePorts(count) {
  const servers = []
  try {
    const ports = []
    for (let index = 0; index < count; index++) {
      const server = createServer()
      servers.push(server)
      server.listen(0, '127.0.0.1')
      await once(server, 'listening')
      const address = server.address()
      if (typeof address !== 'object' || address === null) throw new Error('No test server port')
      ports.push(address.port)
    }
    return ports
  } finally {
    await Promise.all(servers.map((server) => new Promise((resolve) => server.close(resolve))))
  }
}

async function waitFor(url, process, output) {
  for (let attempt = 0; attempt < 200; attempt++) {
    if (process.exitCode !== null) throw new Error(`Server exited with ${process.exitCode}: ${output()}`)
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {
      // The fixture is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error(`Server did not start: ${output()}`)
}

function capture(child) {
  let output = ''
  child.stdout?.on('data', (chunk) => { output += chunk.toString() })
  child.stderr?.on('data', (chunk) => { output += chunk.toString() })
  return () => output
}

async function stopProcess(child) {
  if (child.exitCode !== null) return
  const exited = once(child, 'exit')
  child.kill()
  await Promise.race([exited, new Promise((resolve) => setTimeout(resolve, 5000))])
  if (child.exitCode === null) child.kill('SIGKILL')
}

test('original chat page posts to FastAPI SSE and replays persisted history', async () => {
  if (!existsSync(pythonBin)) throw new Error(`Backend virtualenv Python was not found: ${pythonBin}`)
  const ports = await freePorts(3)
  const [apiPort, controlPort, vitePort] = ports
  const tempDir = await mkdtemp(join(tmpdir(), 'sqlchat-s07-browser-'))
  const fixture = spawn(pythonBin, [apiFixture, '--port', String(apiPort), '--control-port', String(controlPort),
    '--system-db', join(tempDir, 'system.db'), '--app-db', join(tempDir, 'app.db'),
    '--target-db', join(tempDir, 'target.db')], {
    cwd: join(repoDir, 'backend'),
    env: { ...process.env, SQLCHAT_E2E_TARGET_DB: process.env.SQLCHAT_E2E_TARGET_DB ?? '' },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  const fixtureOutput = capture(fixture)
  const vite = spawn(process.execPath, [viteBin, '--host', '127.0.0.1', '--port', String(vitePort), '--strictPort'], {
    cwd: frontendDir,
    env: { ...process.env, VITE_API_PROXY_TARGET: `http://127.0.0.1:${apiPort}` },
    stdio: 'ignore',
  })
  let browser
  let shutdown
  try {
    await waitFor(`http://127.0.0.1:${apiPort}/api/health`, fixture, fixtureOutput)
    await waitFor(`http://127.0.0.1:${vitePort}`, vite, () => '')
    browser = await chromium.launch(existsSync(chromium.executablePath())
      ? { headless: true }
      : { channel: 'chrome', headless: true })
    const page = await browser.newPage()
    const chatPosts = []
    const historyRequests = []
    page.on('request', (request) => {
      const url = new URL(request.url())
      if (url.pathname === '/api/chat' && request.method() === 'POST') {
        chatPosts.push(request.postDataJSON())
      }
      if (/\/api\/chat\/conversations\/\d+\/messages$/.test(url.pathname)) historyRequests.push(url.pathname)
    })
    await page.addInitScript(() => {
      localStorage.setItem('token', 's07-browser-session-token')
      localStorage.setItem('userInfo', JSON.stringify({
        token: 's07-browser-session-token', username: 's07-browser', nickname: 'S07 Browser', role: 'user',
      }))
    })
    await page.goto(`http://127.0.0.1:${vitePort}/admin/chat`)
    await page.locator('.chat-page').waitFor()
    await page.locator('.db-selector .arco-select-view').click()
    await page.getByText('S07 target', { exact: true }).last().click()
    const chatResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname === '/api/chat' && response.request().method() === 'POST')
    await page.locator('.chat-input-area textarea').fill('Count rows in the browser fixture')
    await page.locator('.input-actions button.arco-btn-primary').click()
    const sseResponse = await chatResponse
    assert.equal(sseResponse.status(), 200)
    assert.match(sseResponse.headers()['content-type'], /text\/event-stream/)
    const frames = (await sseResponse.text()).split(/\r?\n/)
      .filter((line) => line.startsWith('data: '))
      .map((line) => JSON.parse(line.slice(6)))
    assert.equal(frames.at(-1)?.type, 'done', `Unexpected SSE terminal sequence: ${JSON.stringify(frames)}`)
    assert.ok(frames.some((event) => event.type === 'summary' &&
      event.content === 'There are 2 rows in the browser fixture.'),
    `Backend did not return the expected summary: ${JSON.stringify(frames)}\n${fixtureOutput()}`)
    assert.equal(frames.filter((event) => event.type === 'summary_delta').map((event) => event.content).join(''),
      'There are 2 rows in the browser fixture.', 'decoded final-report deltas must match the terminal summary')
    await page.locator('.summary-card').getByText('There are 2 rows in the browser fixture.').waitFor()
    assert.equal(await page.locator('.streaming-indicator').count(), 0)
    assert.equal(chatPosts.length, 1, 'the page must submit the write-capable POST once')
    assert.equal(chatPosts[0].message, 'Count rows in the browser fixture')
    assert.equal(chatPosts[0].conversationId, null)
    assert.equal(chatPosts[0].confirmedIntent, null)
    assert.equal(chatPosts[0].dbConfigIds.length, 1)

    assert.ok(frames.some((event) => event.type === 'step' && String(event.content).includes('"count": 2')))
    const conversationId = frames.find((event) => event.type === 'conversation')?.content
    assert.equal(typeof conversationId, 'number')

    await page.goto(`http://127.0.0.1:${vitePort}/admin/conversations`)
    const row = page.locator('tr').filter({ hasText: 'Count rows in the browser fixture' })
    await row.waitFor()
    await row.locator('button:has(.arco-icon-message)').click()
    await page.waitForURL('**/admin/chat')
    await page.locator('.message-bubble.user').getByText('Count rows in the browser fixture').waitFor()
    await page.locator('.summary-card').getByText('There are 2 rows in the browser fixture.').waitFor()
    assert.ok(historyRequests.some((path) => path.endsWith(`/conversations/${conversationId}/messages`)))
    assert.equal(chatPosts.length, 1, 'history replay must use GET and never repeat the chat POST')

    await page.locator('.db-selector .arco-select-view').click()
    await page.getByText('S07 target', { exact: true }).last().click()
    const followupResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname === '/api/chat' && response.request().method() === 'POST')
    await page.locator('.chat-input-area textarea').fill('Count rows again in this conversation')
    await page.locator('.input-actions button.arco-btn-primary').click()
    const secondSse = await followupResponse
    assert.equal(secondSse.status(), 200)
    assert.match(secondSse.headers()['content-type'], /text\/event-stream/)
    const secondFrames = (await secondSse.text()).split(/\r?\n/)
      .filter((line) => line.startsWith('data: '))
      .map((line) => JSON.parse(line.slice(6)))
    assert.equal(secondFrames.at(-1)?.type, 'done')
    assert.ok(secondFrames.some((event) => event.type === 'summary' &&
      event.content === 'The continued query also found 2 rows.'),
    `Follow-up returned an unexpected SSE sequence: ${JSON.stringify(secondFrames)}\n${fixtureOutput()}`)
    assert.equal(secondFrames.filter((event) => event.type === 'summary_delta').map((event) => event.content).join(''),
      'The continued query also found 2 rows.', 'follow-up final-report deltas must match the terminal summary')
    assert.equal(secondFrames.find((event) => event.type === 'conversation')?.content, conversationId)
    await page.locator('.summary-card').last().getByText('The continued query also found 2 rows.').waitFor()
    assert.equal(chatPosts.length, 2)
    assert.equal(chatPosts[1].message, 'Count rows again in this conversation')
    assert.equal(chatPosts[1].conversationId, conversationId)
    assert.equal(chatPosts[1].dbConfigIds.length, 1)

    await page.goto(`http://127.0.0.1:${vitePort}/admin/conversations`)
    const updatedRow = page.locator('tr').filter({ hasText: 'Count rows in the browser fixture' })
    await updatedRow.locator('button:has(.arco-icon-message)').click()
    await page.waitForURL('**/admin/chat')
    await page.locator('.message-bubble.user').getByText('Count rows again in this conversation').waitFor()
    await page.locator('.summary-card').last()
      .getByText('The continued query also found 2 rows.').waitFor()
    assert.equal(historyRequests.filter((path) => path.endsWith(`/conversations/${conversationId}/messages`)).length, 2)
    assert.equal(chatPosts.length, 2, 'continued history replay must not repeat either POST')
    shutdown = await fetch(`http://127.0.0.1:${controlPort}/stop`, { method: 'POST' })
  } finally {
    await browser?.close()
    if (!shutdown) {
      try { await fetch(`http://127.0.0.1:${controlPort}/stop`, { method: 'POST' }) } catch { /* startup failed */ }
    }
    await stopProcess(fixture)
    await stopProcess(vite)
    await rm(tempDir, { recursive: true, force: true })
  }
  assert.match(fixtureOutput(), /S07_TARGET_MODE=(postgresql|mysql|postgresql-sqlite-substitute)/)
})
