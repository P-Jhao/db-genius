import assert from 'node:assert/strict'
import { test } from 'node:test'
import { launchS13Browser, startS13Frontend, stopS13Frontend, success } from './fixtures/s13-browser.mjs'

const supportedTypes = [
  { value: 'mysql', label: 'MySQL', port: 3306 },
  { value: 'postgresql', label: 'PostgreSQL', port: 5432 },
  { value: 'mongodb', label: 'MongoDB', port: 27017 },
  { value: 'mariadb', label: 'MariaDB', port: 3306 },
  { value: 'tidb', label: 'TiDB', port: 4000 },
  { value: 'doris', label: 'Doris', port: 9030 },
  { value: 'starrocks', label: 'StarRocks', port: 9030 },
  { value: 'oceanbase', label: 'OceanBase', port: 2881 },
  { value: 'oracle', label: 'Oracle', port: 1521 },
  { value: 'sqlserver', label: 'SQL Server', port: 1433 },
]

const configs = [
  { id: 21, name: 'Postgres Custom', dbType: 'postgresql', host: 'pg.local', port: 55432,
    dbName: 'analytics', username: 'reader', status: 1, statusDesc: 'Connected', docContent: null,
    docGeneratedAt: null, createdAt: '2026-10-01T10:00:00' },
  { id: 22, name: 'Mongo Auth', dbType: 'mongodb', host: 'mongo.local', port: 27017,
    dbName: 'admin', username: 'mongo-user', status: 1, statusDesc: 'Connected', docContent: null,
    docGeneratedAt: null, createdAt: '2026-10-01T10:00:00' },
  { id: 23, name: 'Legacy Type', dbType: 'legacy', host: 'legacy.local', port: 3333,
    dbName: 'archive', username: 'legacy-user', status: 1, statusDesc: 'Connected', docContent: null,
    docGeneratedAt: null, createdAt: '2026-10-01T10:00:00' },
]

function field(dialog, label) {
  return dialog.locator('.arco-form-item').filter({ hasText: label }).locator('input').first()
}

async function openCreate(page) {
  await page.locator('.page-header button').click()
  const dialog = page.locator('.arco-modal:visible').last()
  await dialog.waitFor()
  return dialog
}

async function chooseType(page, dialog, label) {
  await dialog.locator('.arco-select-view').click()
  await page.locator('.arco-select-option:visible').filter({ hasText: label }).last().click()
}

async function submit(dialog) {
  await dialog.locator('.arco-modal-footer .arco-btn-primary').click({ timeout: 7000 })
}

async function waitForNotice(page, text) {
  await page.getByText(text, { exact: true }).last().waitFor({ state: 'visible' })
}

async function waitForNoticeDismissed(page, text) {
  await page.getByText(text, { exact: true }).last().waitFor({ state: 'hidden' })
}

function expectResponse(page, pathname, method) {
  return page.waitForResponse((response) =>
    new URL(response.url()).pathname === pathname && response.request().method() === method,
  { timeout: 12000 }).then(
    (response) => ({ response }),
    (error) => ({ error }),
  )
}

async function submitAndWait(dialog, responseSignal) {
  await submit(dialog)
  const outcome = await responseSignal
  if ('error' in outcome) throw outcome.error
  return outcome.response
}

test('database type selection and credential submit contracts', async () => {
  const { url, vite } = await startS13Frontend()
  let browser
  const mutations = []
  let failRetryCreateOnce = true
  const observedRequests = []
  const pageErrors = []
  try {
    browser = await launchS13Browser()
    const page = await browser.newPage()
    await page.addInitScript(() => {
      localStorage.setItem('app-locale', 'en')
      localStorage.setItem('token', 's13-db-token')
      localStorage.setItem('userInfo', JSON.stringify({
        token: 's13-db-token', username: 'tester', nickname: 'Tester', role: 'user',
      }))
    })
    page.on('request', (request) => {
      if (new URL(request.url()).pathname.startsWith('/api/')) {
        observedRequests.push(`${request.method()} ${new URL(request.url()).pathname}`)
      }
    })
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await page.route((requestUrl) => new URL(requestUrl).pathname.startsWith('/api/'), async (route) => {
      const request = route.request()
      const pathname = new URL(request.url()).pathname
      if (pathname === '/api/trial/status') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success({ trialEnabled: false })) })
        return
      }
      if (pathname === '/api/db-config' && request.method() === 'GET') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success(configs)) })
        return
      }
      if ((pathname === '/api/db-config' && request.method() === 'POST') ||
        (/^\/api\/db-config\/\d+$/.test(pathname) && request.method() === 'PUT')) {
        const body = request.postDataJSON()
        mutations.push({ method: request.method(), pathname, body })
        if (pathname === '/api/db-config' && body.name === 'Retry After API Failure' && failRetryCreateOnce) {
          failRetryCreateOnce = false
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
            code: 500, message: 'Injected save failure', data: null,
          }) })
          return
        }
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success(null)) })
    })

    await page.goto(`${url}/admin/db-config`)
    await page.locator('.config-card').filter({ hasText: 'Postgres Custom' }).waitFor()
    await page.locator('.page-header button').waitFor({ state: 'visible' })

    let dialog = await openCreate(page)
    const typeSelect = dialog.locator('.arco-select-view')
    let portInput = dialog.locator('.arco-input-number input')
    await typeSelect.click()
    const visibleOptions = page.locator('.arco-select-option')
    await visibleOptions.first().waitFor()
    assert.deepEqual((await visibleOptions.allTextContents()).map((text) => text.trim()),
      supportedTypes.map(({ label }) => label))
    await page.keyboard.press('Escape')
    for (const type of supportedTypes) {
      await chooseType(page, dialog, type.label)
      assert.equal(await portInput.inputValue(), String(type.port), `${type.value} default port`)
    }
    await chooseType(page, dialog, 'MySQL')
    assert.equal(await typeSelect.textContent(), 'MySQL')

    await field(dialog, 'Config Name').fill('MySQL New')
    await field(dialog, 'Host').fill('mysql.local')
    await field(dialog, 'Database Name').fill('analytics')
    await field(dialog, 'Username').fill('reader')
    const beforeInvalidRelationalCreate = mutations.length
    await submit(dialog)
    await waitForNotice(page, 'A password is required when creating a relational database connection.')
    assert.equal(mutations.length, beforeInvalidRelationalCreate, 'missing relational create password must stop before API call')
    assert.equal(await dialog.isVisible(), true, 'credential validation must keep the create modal open')
    assert.equal(await field(dialog, 'Password').inputValue(), '', 'failed validation must preserve form values')
    await field(dialog, 'Password').fill('mysql-secret')
    await waitForNoticeDismissed(page, 'A password is required when creating a relational database connection.')
    const mysqlCreateResponse = expectResponse(page, '/api/db-config', 'POST')
    try {
    await submitAndWait(dialog, mysqlCreateResponse)
    } catch (error) {
      throw new Error(`${error instanceof Error ? error.message : String(error)}; requests=${observedRequests.join(',')}; mutations=${JSON.stringify(mutations)}; pageErrors=${pageErrors.join('|')}; body=${(await page.locator('body').innerText()).slice(0, 1800)}`)
    }
    assert.deepEqual(mutations.at(-1).body, {
      name: 'MySQL New', dbType: 'mysql', host: 'mysql.local', port: 3306, dbName: 'analytics',
      username: 'reader', password: 'mysql-secret',
    })
    await dialog.waitFor({ state: 'hidden' })

    dialog = await openCreate(page)
    await field(dialog, 'Config Name').fill('Retry After API Failure')
    await field(dialog, 'Host').fill('mysql.local')
    await field(dialog, 'Database Name').fill('analytics')
    await field(dialog, 'Username').fill('reader')
    await field(dialog, 'Password').fill('mysql-secret')
    const beforeRetryCreate = mutations.length
    await submitAndWait(dialog, expectResponse(page, '/api/db-config', 'POST'))
    assert.equal(mutations.length, beforeRetryCreate + 1, 'the first API failure issues one create request')
    await waitForNotice(page, 'Injected save failure')
    assert.equal(await dialog.isVisible(), true, 'API failure must keep the create modal open')
    assert.equal(await field(dialog, 'Config Name').inputValue(), 'Retry After API Failure')
    assert.equal(await field(dialog, 'Password').inputValue(), 'mysql-secret')
    assert.equal(mutations.length, beforeRetryCreate + 1, 'API failure must not issue an automatic second request')
    await waitForNoticeDismissed(page, 'Injected save failure')
    await submitAndWait(dialog, expectResponse(page, '/api/db-config', 'POST'))
    assert.equal(mutations.length, beforeRetryCreate + 2, 'the user retry issues exactly one additional create request')
    assert.deepEqual(mutations.at(-1).body, {
      name: 'Retry After API Failure', dbType: 'mysql', host: 'mysql.local', port: 3306, dbName: 'analytics',
      username: 'reader', password: 'mysql-secret',
    })
    await dialog.waitFor({ state: 'hidden' })

    dialog = await openCreate(page)
    portInput = dialog.locator('.arco-input-number input')
    await chooseType(page, dialog, 'MongoDB')
    assert.equal(await portInput.inputValue(), '27017')
    await field(dialog, 'Config Name').fill('Mongo Anonymous')
    await field(dialog, 'Host').fill('mongo.local')
    await field(dialog, 'Database Name').fill('sample')
    const mongoCreateResponse = expectResponse(page, '/api/db-config', 'POST')
    await submitAndWait(dialog, mongoCreateResponse)
    assert.deepEqual(mutations.at(-1).body, {
      name: 'Mongo Anonymous', dbType: 'mongodb', host: 'mongo.local', port: 27017, dbName: 'sample',
      username: '', password: '',
    })
    await dialog.waitFor({ state: 'hidden' })

    dialog = await openCreate(page)
    await chooseType(page, dialog, 'MongoDB')
    await field(dialog, 'Config Name').fill('Mongo Auth New')
    await field(dialog, 'Host').fill('mongo.local')
    await field(dialog, 'Database Name').fill('sample')
    await field(dialog, 'Username').fill('app-user')
    const beforeHalfMongoCreate = mutations.length
    await submit(dialog)
    await waitForNotice(page, 'For MongoDB authentication, enter both username and password or leave both blank.')
    assert.equal(mutations.length, beforeHalfMongoCreate, 'half-paired Mongo credentials must stop before API call')
    assert.equal(await dialog.isVisible(), true, 'Mongo pair validation must keep the create modal open')
    await field(dialog, 'Password').fill('mongo-secret')
    await waitForNoticeDismissed(page, 'For MongoDB authentication, enter both username and password or leave both blank.')
    const mongoAuthCreateResponse = expectResponse(page, '/api/db-config', 'POST')
    await submitAndWait(dialog, mongoAuthCreateResponse)
    assert.deepEqual(mutations.at(-1).body, {
      name: 'Mongo Auth New', dbType: 'mongodb', host: 'mongo.local', port: 27017, dbName: 'sample',
      username: 'app-user', password: 'mongo-secret',
    })
    await dialog.waitFor({ state: 'hidden' })

    const postgresCard = page.locator('.config-card').filter({ hasText: 'Postgres Custom' })
    await postgresCard.locator('.config-actions button').nth(2).click()
    dialog = page.locator('.arco-modal:visible').last()
    await dialog.waitFor()
    assert.equal(await dialog.locator('.arco-select-view').textContent(), 'PostgreSQL')
    assert.equal(await dialog.locator('.arco-input-number input').inputValue(), '55432',
      'opening edit must retain the stored custom port')
    await field(dialog, 'Config Name').fill('Postgres Renamed')
    const beforeRelationalEdit = mutations.length
    const postgresEditResponse = expectResponse(page, '/api/db-config/21', 'PUT')
    await submitAndWait(dialog, postgresEditResponse)
    assert.equal(mutations.length, beforeRelationalEdit + 1)
    assert.deepEqual(mutations.at(-1).body, {
      name: 'Postgres Renamed', dbType: 'postgresql', host: 'pg.local', port: 55432, dbName: 'analytics',
      username: 'reader', password: '',
    }, 'empty relational edit password is sent empty for backend preservation')
    await dialog.waitFor({ state: 'hidden' })

    const mongoCard = page.locator('.config-card').filter({ hasText: 'Mongo Auth' })
    await mongoCard.locator('.config-actions button').nth(2).click()
    dialog = page.locator('.arco-modal:visible').last()
    await dialog.waitFor()
    const beforeHalfMongoEdit = mutations.length
    await submit(dialog)
    await waitForNotice(page, 'For MongoDB authentication, enter both username and password or leave both blank.')
    assert.equal(mutations.length, beforeHalfMongoEdit, 'existing username without re-entered password must be rejected visibly')
    assert.equal(await dialog.isVisible(), true, 'Mongo pair validation must keep the edit modal open')
    await field(dialog, 'Password').fill('mongo-secret')
    await waitForNoticeDismissed(page, 'For MongoDB authentication, enter both username and password or leave both blank.')
    const mongoEditResponse = expectResponse(page, '/api/db-config/22', 'PUT')
    await submitAndWait(dialog, mongoEditResponse)
    assert.deepEqual(mutations.at(-1).body, {
      name: 'Mongo Auth', dbType: 'mongodb', host: 'mongo.local', port: 27017, dbName: 'admin',
      username: 'mongo-user', password: 'mongo-secret',
    })
    await dialog.waitFor({ state: 'hidden' })

    await mongoCard.locator('.config-actions button').nth(2).click()
    dialog = page.locator('.arco-modal:visible').last()
    await dialog.waitFor()
    await field(dialog, 'Username').fill('')
    const mongoAnonymousEditResponse = expectResponse(page, '/api/db-config/22', 'PUT')
    await submitAndWait(dialog, mongoAnonymousEditResponse)
    assert.deepEqual(mutations.at(-1).body, {
      name: 'Mongo Auth', dbType: 'mongodb', host: 'mongo.local', port: 27017, dbName: 'admin',
      username: '', password: '',
    }, 'clearing both Mongo credentials switches the config to anonymous mode')
    await dialog.waitFor({ state: 'hidden' })

    const legacyCard = page.locator('.config-card').filter({ hasText: 'Legacy Type' })
    await legacyCard.locator('.config-actions button').nth(2).click()
    await waitForNotice(page, 'Unsupported database type: legacy. Select a supported type.')
    assert.equal(await page.locator('.arco-modal:visible').count(), 0,
      'an unknown backend type must show an error without silently changing it')
    assert.deepEqual(pageErrors, [])
  } finally {
    await stopS13Frontend(vite, browser)
  }
})
