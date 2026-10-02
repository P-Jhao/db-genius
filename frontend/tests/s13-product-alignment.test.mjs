import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { launchS13Browser, startS13Frontend, stopS13Frontend, success } from './fixtures/s13-browser.mjs'

const sourceDir = fileURLToPath(new URL('../src', import.meta.url))
const locales = [
  { code: 'en', path: '/', question: 'How can I contribute to the project?', button: 'Upload file' },
  { code: 'zh-CN', path: '/zh-CN/', question: '如何为项目贡献？', button: '上传文件' },
  { code: 'zh-TW', path: '/zh-TW/', question: '如何為專案貢獻？', button: '上傳檔案' },
  { code: 'es', path: '/es/', question: '¿Cómo puedo contribuir al proyecto?', button: 'Subir archivo' },
  { code: 'fr', path: '/fr/', question: 'Comment contribuer au projet ?', button: 'Téléverser un fichier' },
  { code: 'ja', path: '/ja/', question: 'プロジェクトに貢献するには？', button: 'ファイルをアップロード' },
  { code: 'ms', path: '/ms/', question: 'Bagaimanakah cara menyumbang kepada projek ini?', button: 'Muat Naik Fail' },
]
const credentialTranslationKeys = [
  'fieldPasswordEditPlaceholder',
  'mongoCredentialsHint',
  'mongoCredentialsPairError',
  'relationalPasswordRequired',
  'unsupportedDatabaseType',
]

test('all landing locales retain routes, localized REST headers, and contribution-only copy', async () => {
  const { url, vite } = await startS13Frontend()
  let browser
  const languages = []
  try {
    browser = await launchS13Browser()
    const page = await browser.newPage()
    await page.addInitScript(() => localStorage.setItem('app-locale', 'en'))
    const observedRequests = []
    page.on('request', (request) => {
      const requestUrl = new URL(request.url())
      if (requestUrl.pathname.startsWith('/api/')) {
        observedRequests.push(`${requestUrl.pathname} accept-language=${request.headers()['accept-language'] ?? ''}`)
      }
    })
    page.on('pageerror', (error) => observedRequests.push(`pageerror:${error.message}`))
    await page.route('**/api/trial/status', async (route) => {
      languages.push(route.request().headers()['accept-language'])
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success({ trialEnabled: false })) })
    })

    for (const locale of locales) {
      const statusResponse = page.waitForResponse((response) =>
        new URL(response.url()).pathname === '/api/trial/status' &&
        response.request().headers()['accept-language'] === locale.code)
      await page.goto(`${url}${locale.path}`)
      await page.locator('.landing-page').waitFor()
      try {
        await statusResponse
      } catch (error) {
        throw new Error(`${error instanceof Error ? error.message : String(error)}; observed: ${observedRequests.join(' | ')}`)
      }
      const faqQuestion = page.locator('.faq .arco-collapse-item-header').filter({ hasText: locale.question })
      await faqQuestion.waitFor()
      assert.equal((await faqQuestion.textContent())?.trim(), locale.question, `${locale.code}: contribution FAQ`)
      const translatedUpload = await page.evaluate(async () => {
        const { i18n, getCurrentLocale } = await import('/src/i18n/index.ts')
        return {
          locale: getCurrentLocale(),
          button: i18n.global.t('chat.uploader.button'),
          sizeLimit: i18n.global.t('chat.uploader.sizeLimit'),
          supportedTypes: i18n.global.t('chat.uploader.unsupportedType', { extensions: '.bmp' }),
          credentialTranslations: Object.fromEntries(
            ['fieldPasswordEditPlaceholder', 'mongoCredentialsHint', 'mongoCredentialsPairError',
              'relationalPasswordRequired', 'unsupportedDatabaseType'].map((key) => [
              key,
              i18n.global.te(`admin.dbConfig.${key}`, getCurrentLocale()),
            ]),
          ),
        }
      })
      assert.equal(translatedUpload.locale, locale.code)
      assert.equal(translatedUpload.button, locale.button)
      assert.match(translatedUpload.sizeLimit, /20 MiB/)
      assert.match(translatedUpload.supportedTypes, /\.bmp/)
      assert.deepEqual(Object.keys(translatedUpload.credentialTranslations), credentialTranslationKeys)
      for (const [key, present] of Object.entries(translatedUpload.credentialTranslations)) {
        assert.equal(present, true, `${locale.code}: translation exists for admin.dbConfig.${key}`)
      }
      assert.equal(languages.at(-1), locale.code, `${locale.code}: trial REST Accept-Language`)
    }
  } finally {
    await stopS13Frontend(vite, browser)
  }
})

test('REST clients retain login, data-source, model, and history paths and request conventions', async () => {
  const { url, vite } = await startS13Frontend()
  let browser
  const requests = []
  try {
    browser = await launchS13Browser()
    const page = await browser.newPage()
    await page.addInitScript(() => localStorage.setItem('app-locale', 'en'))
    await page.route((requestUrl) => new URL(requestUrl).pathname.startsWith('/api/'), async (route) => {
      const request = route.request()
      const requestUrl = new URL(request.url())
      const pathname = requestUrl.pathname
      if (pathname === '/api/trial/status') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success({ trialEnabled: false })) })
        return
      }
      const postData = request.postData()
      requests.push({
        method: request.method(),
        pathname,
        authorization: request.headers().authorization,
        acceptLanguage: request.headers()['accept-language'],
        body: postData ? request.postDataJSON() : null,
      })
      const responseData = pathname === '/api/auth/login'
        ? { token: 'new-token', username: 'tester', nickname: 'Tester', role: 'user' }
        : null
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success(responseData)) })
    })
    await page.goto(url)
    await page.locator('#app').waitFor({ state: 'attached' })

    const results = await page.evaluate(async () => {
      localStorage.setItem('token', 's13-bare-token')
      const pinia = await import('/node_modules/.vite/deps/pinia.js')
      pinia.setActivePinia(pinia.createPinia())
      const i18n = await import('/src/i18n/index.ts')
      i18n.setLocale('es')
      const [auth, db, model, chat] = await Promise.all([
        import('/src/api/auth.ts'),
        import('/src/api/dbConfig.ts'),
        import('/src/api/modelConfig.ts'),
        import('/src/api/chat.ts'),
      ])
      const dbPayload = { name: 'Analytics', dbType: 'postgresql', host: 'db.local', port: 5432,
        dbName: 'analytics', username: 'reader', password: 'secret' }
      const modelPayload = { providerCode: 'custom', providerType: 'openai_compatible', displayName: 'Local',
        baseUrl: 'https://model.invalid/v1', apiKey: 'secret', modelName: 'test-model', contextWindow: 4096 }
      const loginResult = await auth.login({ username: 'tester', password: 'secret' })
      await auth.logout()
      await db.getDbConfigs()
      await db.getDbConfig(7)
      await db.createDbConfig(dbPayload)
      await db.updateDbConfig(7, dbPayload)
      await db.deleteDbConfig(7)
      await db.testDbConfig(7)
      await db.generateDoc(7)
      await db.getDoc(7)
      await model.getModelProviders()
      await model.getModelConfigs()
      await model.createModelConfig(modelPayload)
      await model.updateModelConfig(9, modelPayload)
      await model.deleteModelConfig(9)
      await model.setDefaultModelConfig(9)
      await model.getActiveModelConfig()
      await model.lookupContextWindow({ baseUrl: 'https://model.invalid/v1', apiKey: 'secret', modelName: 'test-model' })
      await model.lookupSavedConfigContextWindow(9)
      await chat.getConversations()
      await chat.getMessages(12)
      await chat.deleteConversation(12)
      await chat.compressConversation(12, 2048)
      return loginResult.data
    })

    assert.equal(results.token, 'new-token')
    assert.deepEqual(requests.map(({ method, pathname }) => [method, pathname]), [
      ['POST', '/api/auth/login'], ['POST', '/api/auth/logout'],
      ['GET', '/api/db-config'], ['GET', '/api/db-config/7'], ['POST', '/api/db-config'],
      ['PUT', '/api/db-config/7'], ['DELETE', '/api/db-config/7'], ['POST', '/api/db-config/7/test'],
      ['POST', '/api/db-config/7/generate-doc'], ['GET', '/api/db-config/7/doc'],
      ['GET', '/api/model-config/providers'], ['GET', '/api/model-config/configs'],
      ['POST', '/api/model-config/configs'], ['PUT', '/api/model-config/configs/9'],
      ['DELETE', '/api/model-config/configs/9'], ['PUT', '/api/model-config/configs/9/default'],
      ['GET', '/api/model-config/active'], ['POST', '/api/model-config/context-window/lookup'],
      ['GET', '/api/model-config/configs/9/context-window'],
      ['GET', '/api/chat/conversations'], ['GET', '/api/chat/conversations/12/messages'],
      ['DELETE', '/api/chat/conversations/12'], ['POST', '/api/chat/conversations/12/compress'],
    ])
    for (const request of requests) {
      assert.equal(request.authorization, 's13-bare-token', `${request.method} ${request.pathname}: bare token`)
      assert.equal(request.acceptLanguage, 'es', `${request.method} ${request.pathname}: locale header`)
    }
    assert.deepEqual(requests[2].body, null)
    assert.deepEqual(requests[4].body, {
      name: 'Analytics', dbType: 'postgresql', host: 'db.local', port: 5432,
      dbName: 'analytics', username: 'reader', password: 'secret',
    })
    assert.equal(requests[12].body.providerCode, 'custom')
    assert.equal(requests[12].body.contextWindow, 4096)
    assert.deepEqual(requests.at(-1).body, { targetTokens: 2048 })
  } finally {
    await stopS13Frontend(vite, browser)
  }
})

test('the route table retains original pages and the sales-contact path is absent', () => {
  const router = readFileSync(new URL('../src/router/index.ts', import.meta.url), 'utf8')
  assert.match(router, /path: '\/login'/)
  for (const path of ['chat', 'db-config', 'model-config', 'conversations']) {
    assert.match(router, new RegExp(`path: '${path}'`), `missing admin route ${path}`)
  }
  assert.match(router, /meta: \{ requiresAuth: true \}/)
  assert.doesNotMatch(router, /sales|contact/i)

  const sourceFiles = []
  function collectFiles(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name)
      if (entry.isDirectory()) collectFiles(path)
      else if (/\.(vue|ts|tsx|js)$/.test(entry.name)) sourceFiles.push(path)
    }
  }
  collectFiles(sourceDir)
  const source = sourceFiles.map((path) => readFileSync(path, 'utf8')).join('\n')
  assert.doesNotMatch(source, /sales\/contact|salesContact|contact us|partnership|\bpartner(ship)?\b|联系销售|销售联系|協業|bekerjasama/i)
  assert.doesNotMatch(source, /如何为项目合作|如何為專案合作/)
})
