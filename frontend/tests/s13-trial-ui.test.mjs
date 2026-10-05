import assert from 'node:assert/strict'
import { test } from 'node:test'
import { launchS13Browser, startS13Frontend, stopS13Frontend, success } from './fixtures/s13-browser.mjs'

test('upload stays available while unknown and trial statuses retain other restricted UI rules', async () => {
  const { url, vite } = await startS13Frontend()
  let browser
  let statusCalls = 0
  const apiCalls = []
  try {
    browser = await launchS13Browser()
    const createPage = async () => {
      const newPage = await browser.newPage()
      await newPage.addInitScript(() => {
        localStorage.setItem('app-locale', 'en')
        localStorage.setItem('token', 's13-trial-token')
        localStorage.setItem('userInfo', JSON.stringify({
          token: 's13-trial-token', username: 'trial-user', nickname: 'Trial User', role: 'user',
        }))
      })
      await newPage.route((requestUrl) => new URL(requestUrl).pathname.startsWith('/api/'), async (route) => {
        const request = route.request()
        const pathname = new URL(request.url()).pathname
        if (pathname === '/api/trial/status') {
          statusCalls += 1
          if (statusCalls === 1) {
            await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ message: 'Unavailable' }) })
          } else {
            await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success({ trialEnabled: true })) })
          }
          return
        }
        apiCalls.push({ method: request.method(), pathname })
        let data = null
        if (pathname === '/api/file/upload') {
          assert.equal(request.method(), 'POST')
          assert.match(request.headers()['content-type'], /^multipart\/form-data; boundary=/)
          const uploadedName = (request.postData() ?? '').match(/name="file"; filename="([^"]+)"/)?.[1]
          assert.ok(['sample.xlsx', 'sample.xls', 'formal.csv'].includes(uploadedName))
          data = { id: 41 + apiCalls.filter(({ pathname }) => pathname === '/api/file/upload').length,
            originalName: uploadedName, fileSize: 6,
            contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            createdAt: '2026-10-05T10:00:00' }
        } else if (pathname === '/api/db-config') {
          data = [{ id: 1, name: 'Trial database', dbType: 'mysql', host: '127.0.0.1', port: 3306,
            dbName: 'sample', username: 'reader', status: 1, statusDesc: 'Connected', docContent: '',
            docGeneratedAt: null, createdAt: '2026-09-30T10:00:00' }]
        } else if (pathname === '/api/model-config/active') {
          data = { id: null, providerCode: 'system', providerType: 'openai_compatible', displayName: 'Built-in Model',
            baseUrl: 'https://model.invalid/v1', modelName: 'trial-model', contextWindow: null,
            isDefault: true, status: 1, statusDesc: 'Enabled', createdAt: '2026-09-30T10:00:00' }
        } else if (pathname === '/api/chat/conversations') {
          data = []
        }
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success(data)) })
      })
      return newPage
    }

    const page = await createPage()
    await page.goto(url)
    await page.locator('.trial-status-alert').waitFor()
    assert.match(await page.locator('.trial-status-alert').textContent(), /could not|unavailable/i)
    const navigate = async (path) => page.evaluate(async (nextPath) => {
      const { default: router } = await import('/src/router/index.ts')
      await router.push(nextPath)
    }, path)

    await navigate('/admin/chat')
    await page.locator('.chat-page').waitFor()
    assert.equal(await page.locator('.file-uploader').count(), 1, 'upload is available independently of trial status')
    const uploadInput = page.locator('.file-uploader input[type="file"]')
    assert.equal(await uploadInput.getAttribute('accept'), '.xlsx,.xls')
    assert.equal(await page.locator('.file-uploader').getByRole('button', { name: 'Upload Excel', exact: true }).count(), 1)
    await Promise.all([
      page.getByText('Supported formats: .xlsx, .xls', { exact: true }).waitFor(),
      uploadInput.setInputFiles({ name: 'unknown.csv', mimeType: 'text/csv', buffer: Buffer.from('id\n1') }),
    ])
    assert.equal(apiCalls.filter(({ pathname }) => pathname === '/api/file/upload').length, 0)
    assert.equal(await page.getByRole('button', { name: 'Compare', exact: true }).count(), 0,
      'unknown status must not expose database comparison')

    const retryButton = page.locator('.trial-status-alert button')
    await retryButton.waitFor()
    await retryButton.click()
    await page.locator('.trial-status-alert').waitFor({ state: 'detached' })
    assert.equal(statusCalls, 2)

    const dbPage = await createPage()
    await dbPage.goto(`${url}/admin/db-config`)
    await dbPage.locator('.config-card').filter({ hasText: 'Trial database' }).waitFor()
    assert.equal(await dbPage.locator('.page-header button').count(), 0, 'trial database page must not offer create')
    const dbActions = dbPage.locator('.config-card').filter({ hasText: 'Trial database' }).locator('.config-actions button')
    assert.equal(await dbActions.count(), 1, 'only read-only documentation action remains on a trial DB')

    const modelPage = await createPage()
    await modelPage.goto(`${url}/admin/model-config`)
    await modelPage.getByText('Built-in Model', { exact: true }).waitFor()
    assert.equal(await modelPage.locator('.page-header button').count(), 0, 'trial model page must not offer create')

    assert.equal(await page.locator('.file-uploader').count(), 1, 'trial mode retains upload')
    assert.equal(await uploadInput.getAttribute('accept'), '.xlsx,.xls')
    assert.equal(await page.locator('.file-uploader').getByRole('button', { name: 'Upload Excel', exact: true }).count(), 1)
    await Promise.all([
      page.getByText('Supported formats: .xlsx, .xls', { exact: true }).waitFor(),
      uploadInput.setInputFiles({ name: 'trial.pdf', mimeType: 'application/pdf', buffer: Buffer.from('sample') }),
    ])
    assert.equal(apiCalls.filter(({ pathname }) => pathname === '/api/file/upload').length, 0)
    await page.locator('.file-uploader input[type="file"]').setInputFiles({
      name: 'sample.xlsx',
      mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      buffer: Buffer.from('sample'),
    })
    await page.locator('.file-list').getByText('sample.xlsx', { exact: false }).waitFor()
    assert.equal(apiCalls.filter(({ pathname }) => pathname === '/api/file/upload').length, 1,
      'trial chat upload reaches the existing API')
    await uploadInput.setInputFiles({ name: 'sample.xls', mimeType: 'application/vnd.ms-excel', buffer: Buffer.from('sample') })
    await page.locator('.file-list').getByText('sample.xls', { exact: false }).waitFor()
    assert.equal(apiCalls.filter(({ pathname }) => pathname === '/api/file/upload').length, 2)
    assert.equal(await page.getByRole('button', { name: 'Compare', exact: true }).count(), 0,
      'trial mode must hide comparison')
    assert.equal(apiCalls.some(({ method, pathname }) => method !== 'GET' &&
      /\/(db-config|model-config\/configs|model-config\/context-window\/lookup)(\/|$)/.test(pathname)), false,
    'other restricted mutation and lookup calls remain blocked')
    await page.evaluate(async () => {
      const { useTrialStore } = await import('/src/stores/trial.ts')
      useTrialStore().trialEnabled = false
    })
    assert.equal(await uploadInput.getAttribute('accept'), '.xlsx,.xls,.csv,.docx,.pdf,.md,.png,.jpg,.jpeg,.webp,.bmp')
    assert.equal(await page.locator('.file-uploader').getByRole('button', { name: 'Upload file', exact: true }).count(), 1)
    await uploadInput.setInputFiles({ name: 'formal.csv', mimeType: 'text/csv', buffer: Buffer.from('id\n1') })
    await page.locator('.file-list').getByText('formal.csv', { exact: false }).waitFor()
    assert.equal(apiCalls.filter(({ pathname }) => pathname === '/api/file/upload').length, 3,
      'resolved formal mode restores CSV uploads')
  } finally {
    await stopS13Frontend(vite, browser)
  }
})
