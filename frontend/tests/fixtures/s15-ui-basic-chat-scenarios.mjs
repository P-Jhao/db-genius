import assert from 'node:assert/strict'
import { join } from 'node:path'
import { capture, clickMenu, makePage, waitForVisualStability } from './s15-ui-scenario-shared.mjs'

const conversationTitle = 'Quarterly account totals'

async function runBasicChatScenarios({
  browser, url, api, screenshotDir, screenshots, onlyScenario, pageErrors, stopCancellation,
}) {
  let activeChatRequest = null
  let expectedStopAbortRequest = null
  const page = await makePage(browser)
  page.on('pageerror', (error) => pageErrors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') pageErrors.push(`console:${message.text()}`)
  })
  page.on('request', (request) => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/chat') {
      activeChatRequest = request
    }
  })
  page.on('requestfinished', (request) => {
    if (request === activeChatRequest) activeChatRequest = null
  })
  page.on('requestfailed', (request) => {
    const errorText = request.failure()?.errorText ?? ''
    const isExpectedStopAbort = request === expectedStopAbortRequest &&
      request.method() === 'POST' && new URL(request.url()).pathname === '/api/chat' &&
      errorText === 'net::ERR_ABORTED'
    if (isExpectedStopAbort) {
      stopCancellation.push({ method: request.method(), path: new URL(request.url()).pathname, errorText })
    } else {
      pageErrors.push(`request:${request.url()} ${errorText}`)
    }
    if (request === activeChatRequest) activeChatRequest = null
  })
  page.on('response', (response) => {
    if (response.status() >= 400) {
      void response.text().then((body) => pageErrors.push(`response:${response.status()} ${response.url()} ${body.slice(0, 1200)}`))
    }
  })
  await page.goto(`${url}/`)
  try {
    await page.locator('.landing-page').waitFor({ timeout: 8000 })
  } catch (error) {
    const bodyText = (await page.locator('body').innerText()).slice(0, 800)
    await page.screenshot({ path: join(screenshotDir, 'landing-not-ready.png'), fullPage: true })
    throw new Error(`Landing page did not render; title=${await page.title()}; body=${bodyText}; browser=${pageErrors.join(' | ')}; cause=${String(error)}`)
  }
  await capture(page, screenshotDir, screenshots, 'landing', onlyScenario)
  await page.getByRole('button', { name: 'Sign In', exact: true }).click()
  await page.waitForURL('**/login')
  await capture(page, screenshotDir, screenshots, 'login', onlyScenario)
  await page.getByPlaceholder('Enter your username').fill('s15-reviewer')
  await page.getByPlaceholder('Enter your password').fill('fixture-password')
  await page.getByRole('button', { name: 'Log In', exact: true }).click()
  try {
    await page.locator('.chat-page').waitFor()
  } catch (error) {
    const routeState = await page.evaluate(async () => {
      const router = await import('/src/router/index.ts')
      return {
        location: window.location.href,
        route: router.default.currentRoute.value.fullPath,
        body: document.body.innerText.slice(0, 800),
      }
    })
    throw new Error(`Login did not render chat: ${JSON.stringify(routeState)}; API=${JSON.stringify(api.requests)}; ${String(error)}`)
  }
  const loginSuccessToast = page.locator('.arco-message').filter({ hasText: 'Logged in successfully' })
  await loginSuccessToast.waitFor({ state: 'visible' })
  assert.equal(await loginSuccessToast.count(), 1,
    'successful login must show the exact login-success notification before it expires')
  await page.locator('.empty-chat').waitFor()
  await capture(page, screenshotDir, screenshots, 'chat-empty', onlyScenario)

  await clickMenu(page, 'Database Config', '/admin/db-config')
  await page.locator('.config-card').filter({ hasText: 'Analytics Fixture' }).waitFor()
  await capture(page, screenshotDir, screenshots, 'database-config', onlyScenario)
  await page.getByRole('button', { name: 'New Config', exact: true }).click()
  const dbCreateDialog = page.locator('.arco-modal-wrapper:visible').filter({ hasText: 'New Config' })
  await dbCreateDialog.waitFor({ state: 'visible' })
  await page.waitForTimeout(450)
  await capture(page, screenshotDir, screenshots, 'database-create-dialog', onlyScenario)
  await dbCreateDialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await dbCreateDialog.waitFor({ state: 'hidden' })
  const dbCard = page.locator('.config-card').filter({ hasText: 'Analytics Fixture' })
  await dbCard.locator('.config-actions button').last().click()
  await page.getByText('Are you sure you want to delete the database config', { exact: false }).waitFor()
  await page.waitForTimeout(450)
  if (onlyScenario === 'database-delete-confirm') {
    await loginSuccessToast.waitFor({ state: 'detached', timeout: 8000 })
  }
  await capture(page, screenshotDir, screenshots, 'database-delete-confirm', onlyScenario)
  if (onlyScenario === 'database-delete-confirm') {
    assert.deepEqual(pageErrors, [], 'browser pages must not report uncaught errors')
    await page.close()
    return true
  }
  const deleteDialog = page.locator('.arco-modal-wrapper:visible').filter({
    hasText: 'Are you sure you want to delete the database config',
  })
  await deleteDialog.waitFor({ state: 'visible' })
  await page.keyboard.press('Escape')
  await deleteDialog.waitFor({ state: 'hidden' })

  await clickMenu(page, 'Model Config', '/admin/model-config')
  try {
    await page.locator('.config-card').filter({ hasText: 'Fixture Model' }).waitFor({ timeout: 8000 })
  } catch (error) {
    const bodyText = (await page.locator('body').innerText()).slice(0, 1200)
    await capture(page, screenshotDir, screenshots, 'model-config-debug', onlyScenario)
    throw new Error(`Model config did not render at ${page.url()}; body=${bodyText}; cause=${String(error)}`)
  }
  await capture(page, screenshotDir, screenshots, 'model-config', onlyScenario)
  await page.getByRole('button', { name: 'New Config', exact: true }).click()
  const modelCreateDialog = page.locator('.arco-modal-wrapper:visible').filter({ hasText: 'New Config' })
  await modelCreateDialog.waitFor({ state: 'visible' })
  await page.waitForTimeout(450)
  await capture(page, screenshotDir, screenshots, 'model-create-dialog', onlyScenario)
  await modelCreateDialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await modelCreateDialog.waitFor({ state: 'hidden' })

  await clickMenu(page, 'Conversations', '/admin/conversations')
  await loginSuccessToast.waitFor({ state: 'detached', timeout: 8000 })
  const conversationsPage = page.locator('.page-container')
  const historyRow = page.locator('tr').filter({ hasText: conversationTitle })
  await historyRow.waitFor({ state: 'visible' })
  await waitForVisualStability(conversationsPage, 'conversation list page')
  await waitForVisualStability(historyRow, 'conversation history row')
  await capture(page, screenshotDir, screenshots, 'conversation-list', onlyScenario)
  await historyRow.getByText(conversationTitle, { exact: true }).click()
  const historyDrawer = page.locator('.arco-drawer').filter({ hasText: conversationTitle })
  await historyDrawer.waitFor({ state: 'visible' })
  const historyDrawerMask = historyDrawer.locator('xpath=..').locator('.arco-drawer-mask')
  const historyUserMessage = historyDrawer.getByText('Count active accounts.', { exact: true })
  const historySummary = historyDrawer.getByText('There are 2 active accounts.', { exact: true })
  await historyUserMessage.waitFor({ state: 'visible' })
  await historySummary.waitFor({ state: 'visible' })
  await waitForVisualStability(historyDrawerMask, 'conversation history drawer mask')
  await waitForVisualStability(historyUserMessage, 'conversation history user message')
  await waitForVisualStability(historySummary, 'conversation history assistant summary')
  await capture(page, screenshotDir, screenshots, 'conversation-history-drawer', onlyScenario)
  await page.keyboard.press('Escape')
  await historyUserMessage.waitFor({ state: 'hidden' })
  await historyRow.locator('button').nth(1).click()
  await page.waitForURL('**/admin/chat')
  const replayPage = page.locator('.chat-page')
  const replaySummary = page.locator('.summary-card').filter({ hasText: 'There are 2 active accounts.' })
  await replaySummary.waitFor({ state: 'visible' })
  await waitForVisualStability(replayPage, 'chat history replay page')
  await waitForVisualStability(replaySummary, 'chat history replay summary')
  await capture(page, screenshotDir, screenshots, 'chat-history-replay', onlyScenario)

  await page.getByRole('button', { name: 'New Chat', exact: true }).click()
  await page.locator('.chat-input-area textarea').fill('Need clarification for a query')
  await page.getByRole('button', { name: 'Send', exact: true }).click()
  const clarifyCard = page.locator('.clarify-card')
  await clarifyCard.waitFor()
  assert.match(await clarifyCard.innerText(), /Which kind of result do you want\?/)
  await capture(page, screenshotDir, screenshots, 'chat-clarification', onlyScenario)
  await clarifyCard.getByRole('button', { name: 'SQL query', exact: true }).click()
  await page.locator('.summary-card').filter({ hasText: 'The query found two active accounts.' }).waitFor()
  await capture(page, screenshotDir, screenshots, 'chat-steps-summary', onlyScenario)
  assert.equal(api.chatRequests[1]?.body?.confirmedIntent, 'sql_query')

  await page.getByRole('button', { name: 'New Chat', exact: true }).click()
  await page.locator('.chat-input-area textarea').fill('Hold response for the stop control')
  await page.getByRole('button', { name: 'Send', exact: true }).click()
  await page.locator('.step-card.thinking').waitFor()
  await page.getByRole('button', { name: 'Stop', exact: true }).waitFor()
  const requestToStop = activeChatRequest
  assert.ok(requestToStop, 'Stop must target an active chat POST request')
  const requestFailure = page.waitForEvent('requestfailed', {
    predicate: (request) => request === requestToStop,
    timeout: 5000,
  })
  expectedStopAbortRequest = requestToStop
  await page.getByRole('button', { name: 'Stop', exact: true }).click()
  const stoppedRequest = await requestFailure
  assert.equal(stoppedRequest.failure()?.errorText, 'net::ERR_ABORTED',
    'only the Stop click should abort this exact chat request')
  await page.getByRole('button', { name: 'Send', exact: true }).waitFor()
  await capture(page, screenshotDir, screenshots, 'chat-stopped', onlyScenario)
  assert.equal(api.chatRequests[2]?.clientAborted, true, 'stop click must close the in-flight SSE request')
  assert.deepEqual(stopCancellation, [{ method: 'POST', path: '/api/chat', errorText: 'net::ERR_ABORTED' }])
  await page.close()
  return false
}

export { runBasicChatScenarios }
