import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { existsSync, readFileSync, writeFileSync, unlinkSync } from 'node:fs'
import { createServer } from 'node:net'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import { chromium } from 'playwright'

const frontendDir = fileURLToPath(new URL('..', import.meta.url))
const typesPath = fileURLToPath(new URL('../src/types/index.ts', import.meta.url))
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
      // Vite is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error('Vite did not start within 10 seconds')
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

test('FileUploader consumes the backend VO and displays API failures', async () => {
  const port = await freePort()
  const url = `http://127.0.0.1:${port}`
  const configPath = fileURLToPath(new URL('../.s10-test-vite.config.mjs', import.meta.url))
  writeFileSync(configPath, `import config from './vite.config.ts';
export default { ...config, server: { ...config.server, fs: { strict: true,
  allow: [${JSON.stringify(frontendDir)}],
  deny: ['.env', '.env.*', '*.{crt,pem,key,p12,pfx,cer,der}', '.npmrc', '.yarnrc.yml']
} } };`)
  const vite = spawn(process.execPath, [viteBin, '--config', configPath, '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
    cwd: frontendDir,
    stdio: 'ignore', env: { ...process.env, VITE_API_BASE_URL: '/api' },
  })
  let browser
  let uploads = 0
  try {
    await waitForVite(url, vite)
    browser = await chromium.launch(existsSync(chromium.executablePath())
      ? { headless: true }
      : { channel: 'chrome', headless: true })
    const page = await browser.newPage()
    const pageErrors = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await page.route('**/api/file/upload', async (route) => {
      const request = route.request()
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
    await page.goto(url)
    await page.evaluate(async () => {
      const [vue, component, i18nModule, arcoModule, iconModule, piniaModule] = await Promise.all([
        import('/node_modules/.vite/deps/vue.js'),
        import('/src/components/chat/FileUploader.vue'),
        import('/src/i18n/index.ts'),
        import('/node_modules/.vite/deps/@arco-design_web-vue.js'),
        import('/node_modules/.vite/deps/@arco-design_web-vue_es_icon.js'),
        import('/node_modules/.vite/deps/pinia.js'),
      ])
      const app = vue.createApp(component.default)
      app.use(piniaModule.createPinia())
      app.use(i18nModule.i18n)
      app.use(arcoModule.default)
      app.use(iconModule.default)
      const mountPoint = document.createElement('div')
      mountPoint.id = 'upload-contract-test'
      document.body.append(mountPoint)
      app.mount(mountPoint)
    })

    const input = page.locator('#upload-contract-test input[type="file"]')
    assert.equal(await input.getAttribute('accept'),
      '.xlsx,.xls,.csv,.docx,.pdf,.md,.png,.jpg,.jpeg,.webp,.bmp')
    const uploadFile = (name, mimeType, buffer = Buffer.from('sample upload')) => ({
      name,
      mimeType,
      buffer,
    })

    await input.setInputFiles(uploadFile('unsupported.txt', 'text/plain'))
    await page.getByText(/Supported formats: \.xlsx, \.xls, \.csv/).waitFor()
    assert.equal(uploads, 0, 'unsupported extensions are stopped before the request')

    await input.setInputFiles(uploadFile('oversized.pdf', 'application/pdf', Buffer.alloc(20 * 1024 * 1024 + 1)))
    await page.getByText('File size must not exceed 20 MiB', { exact: true }).waitFor()
    assert.equal(uploads, 0, 'files over the backend limit are stopped before the request')

    const uploadResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname === '/api/file/upload')
    await input.setInputFiles(uploadFile('quarter.pdf', 'application/pdf'))
    assert.equal((await uploadResponse).status(), 200)
    assert.equal(uploads, 1, 'the valid file must reach the upload endpoint')
    const fileTag = page.locator('#upload-contract-test .file-list')
    await page.waitForTimeout(250)
    assert.match(await fileTag.textContent() ?? '', /quarter\.pdf/, `upload UI failed; page errors: ${pageErrors.join(' | ')}`)
    assert.match(await fileTag.textContent() ?? '', /quarter\.pdf\s*\(—\)/)
    assert.doesNotMatch(await fileTag.textContent(), /undefined|NaN/)

    await input.setInputFiles(uploadFile('rejected.pdf', 'application/pdf'))
    await page.getByText('Upload rejected', { exact: true }).waitFor()
    assert.equal(await fileTag.getByText('quarter.pdf', { exact: false }).count(), 1)

    await input.setInputFiles(uploadFile('storage-error.pdf', 'application/pdf'))
    await page.getByText('Storage temporarily unavailable', { exact: true }).waitFor()
    assert.equal(uploads, 3)
  } finally {
    await browser?.close()
    vite.kill()
    if (vite.exitCode === null) await once(vite, 'exit')
    unlinkSync(configPath)
  }
})
