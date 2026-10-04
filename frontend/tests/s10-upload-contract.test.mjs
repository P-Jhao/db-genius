import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { existsSync, readFileSync } from 'node:fs'
import { mkdtemp } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import { chromium } from 'playwright'

const frontendDir = fileURLToPath(new URL('..', import.meta.url))
const typesPath = fileURLToPath(new URL('../src/types/index.ts', import.meta.url))
const viteBin = fileURLToPath(new URL('../node_modules/vite/bin/vite.js', import.meta.url))
const configPath = fileURLToPath(new URL('./fixtures/s10-test-vite.config.mjs', import.meta.url))
const fixturePath = '/tests/fixtures/s10-upload-component.html'

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

async function waitForVite(url, process, output) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (process.exitCode !== null) throw new Error(`Vite exited with ${process.exitCode}: ${output()}`)
    try {
      if ((await fetch(url)).ok) return
    } catch {
      // Vite is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error(`Vite did not start within 10 seconds: ${output()}`)
}

test('UploadedFile matches the public upload VO exactly, including nullable fields', () => {
  const sourceText = readFileSync(typesPath, 'utf8')
  const source = ts.createSourceFile(typesPath, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
  const declaration = source.statements.find((statement) =>
    ts.isInterfaceDeclaration(statement) && statement.name.text === 'UploadedFile')
  assert.ok(declaration && ts.isInterfaceDeclaration(declaration), 'UploadedFile interface exists')

  const properties = new Map(declaration.members.flatMap((member) => {
    if (!ts.isPropertySignature(member) || !member.name || !member.type) return []
    return [[member.name.getText(source), member.type.getText(source)]]
  }))
  assert.deepEqual([...properties.keys()].sort(), [
    'contentType', 'createdAt', 'fileSize', 'id', 'originalName',
  ])
  assert.deepEqual(Object.fromEntries(properties), {
    id: 'number',
    originalName: 'string',
    fileSize: 'number | null',
    contentType: 'string | null',
    createdAt: 'string',
  })
})

test('FileUploader consumes the backend VO and displays API failures', async (t) => {
  const port = await freePort()
  const url = `http://127.0.0.1:${port}`
  const cacheDir = await mkdtemp(join(tmpdir(), 'sqlchat-s10-vite-cache-'))
  const vite = spawn(process.execPath, [viteBin, '--config', configPath, '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
    cwd: frontendDir,
    stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, SQLCHAT_TEST_VITE_CACHE_DIR: cacheDir },
  })
  let viteOutput = ''
  vite.stdout.on('data', (chunk) => { viteOutput += chunk.toString() })
  vite.stderr.on('data', (chunk) => { viteOutput += chunk.toString() })
  let browser
  let uploads = 0
  try {
    await waitForVite(url + fixturePath, vite, () => viteOutput)
    browser = await chromium.launch(existsSync(chromium.executablePath())
      ? { headless: true }
      : { channel: 'chrome', headless: true })
    const page = await browser.newPage()
    const pageErrors = []
    const unexpectedRequests = []
    const navigations = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    page.on('request', (request) => {
      if (request.isNavigationRequest() && request.frame() === page.mainFrame()) navigations.push(request.url())
    })
    await page.route('**/*', async (route) => {
      const request = route.request()
      const requestUrl = new URL(request.url())
      const isApi = requestUrl.pathname === '/api' || requestUrl.pathname.startsWith('/api/')
      if (requestUrl.origin !== url || (isApi && requestUrl.pathname !== '/api/file/upload')) {
        unexpectedRequests.push(`${request.method()} ${requestUrl.origin}${requestUrl.pathname}`)
        await route.abort()
        return
      }
      if (requestUrl.pathname !== '/api/file/upload') {
        await route.continue()
        return
      }
      assert.equal(request.method(), 'POST')
      assert.match(request.headers()['content-type'], /^multipart\/form-data; boundary=/)
      assert.match(request.postData() ?? '', /name="file"/)
      uploads += 1

      if (uploads === 1) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            code: 200,
            message: 'success',
            data: {
              id: 41,
              originalName: 'quarter.pdf',
              fileSize: null,
              contentType: null,
              createdAt: '2026-09-29T12:34:56',
            },
          }),
        })
        return
      }
      if (uploads === 2) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ code: 400, message: 'Upload rejected', data: null }),
        })
        return
      }
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ message: 'Storage temporarily unavailable' }),
      })
    })

    await page.addInitScript(() => localStorage.setItem('app-locale', 'en'))
    await page.goto(url + fixturePath)

    const input = page.locator('#upload-contract-test input[type="file"]')
    await input.waitFor({ state: 'attached' })
    assert.equal(await input.getAttribute('accept'),
      '.xlsx,.xls,.csv,.docx,.pdf,.md,.png,.jpg,.jpeg,.webp,.bmp')
    const uploadFile = (name, mimeType, buffer = Buffer.from('sample upload')) => ({
      name,
      mimeType,
      buffer,
    })

    await Promise.all([
      page.getByText(/Supported formats: \.xlsx, \.xls, \.csv/).waitFor(),
      input.setInputFiles(uploadFile('unsupported.txt', 'text/plain')),
    ])
    assert.equal(uploads, 0, 'unsupported extensions are stopped before the request')

    await Promise.all([
      page.getByText('File size must not exceed 20 MiB', { exact: true }).waitFor(),
      input.setInputFiles(uploadFile('oversized.pdf', 'application/pdf', Buffer.alloc(20 * 1024 * 1024 + 1))),
    ])
    assert.equal(uploads, 0, 'files over the backend limit are stopped before the request')

    const uploadResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname === '/api/file/upload')
    await input.setInputFiles(uploadFile('quarter.pdf', 'application/pdf'))
    assert.equal((await uploadResponse).status(), 200)
    assert.equal(uploads, 1, 'the valid file must reach the upload endpoint')
    const fileTag = page.locator('#upload-contract-test .file-list')
    await fileTag.getByText('quarter.pdf', { exact: false }).waitFor()
    assert.match(await fileTag.textContent() ?? '', /quarter\.pdf/, `upload UI failed; page errors: ${pageErrors.join(' | ')}`)
    assert.match(await fileTag.textContent() ?? '', /quarter\.pdf\s*\(—\)/)
    assert.doesNotMatch(await fileTag.textContent(), /undefined|NaN/)

    await Promise.all([
      page.getByText('Upload rejected', { exact: true }).waitFor(),
      input.setInputFiles(uploadFile('rejected.pdf', 'application/pdf')),
    ])
    assert.equal(await fileTag.getByText('quarter.pdf', { exact: false }).count(), 1)

    await Promise.all([
      page.getByText('Storage temporarily unavailable', { exact: true }).waitFor(),
      input.setInputFiles(uploadFile('storage-error.pdf', 'application/pdf')),
    ])
    assert.equal(uploads, 3)
    assert.deepEqual(unexpectedRequests, [], 'the component fixture must use only its mocked upload API')
    assert.deepEqual(pageErrors, [], `unexpected browser errors; Vite output: ${viteOutput}`)
    assert.deepEqual(navigations, [url + fixturePath], 'the fixture must remain mounted throughout the upload assertions')
    t.diagnostic('isolated cold Vite cache; one document navigation; three mocked uploads; no other HTTP APIs')
  } finally {
    await browser?.close()
    if (vite.exitCode === null) {
      const exited = once(vite, 'exit')
      vite.kill()
      await exited
    }
  }
})
