import assert from 'node:assert/strict'
import { capture, clickMenu, makePage } from './s15-ui-scenario-shared.mjs'

async function runDataSourceTrialScenarios({
  browser, url, api, screenshotDir, screenshots, onlyScenario, trialUploadExpectation, uiAssertionFailures,
}) {
  api.setProfile('empty')
  const emptyPage = await makePage(browser, 's15-fixture-token')
  await emptyPage.goto(`${url}/admin/db-config`)
  await emptyPage.locator('.empty-card').waitFor()
  await capture(emptyPage, screenshotDir, screenshots, 'database-empty', onlyScenario)
  await emptyPage.close()

  api.setProfile('error')
  const errorPage = await makePage(browser, 's15-fixture-token')
  await errorPage.goto(`${url}/admin/db-config`)
  await errorPage.getByText('Fixture database unavailable', { exact: true }).waitFor()
  await capture(errorPage, screenshotDir, screenshots, 'database-error', onlyScenario)
  await errorPage.close()

  api.reset()
  api.setProfile('trial')
  const trialPage = await makePage(browser, 's15-fixture-token')
  await trialPage.goto(`${url}/admin/db-config`)
  const trialCard = trialPage.locator('.config-card').filter({ hasText: 'Built-in Test Database' })
  await trialCard.waitFor()
  const trialText = await trialCard.innerText()
  for (const privateValue of ['db.fixture.invalid', 'analytics_fixture', 'fixture_reader']) {
    assert.equal(trialText.includes(privateValue), false, `trial UI must not display ${privateValue}`)
  }
  assert.equal(api.requests.some((request) => request.method !== 'GET'), false,
    'trial screenshots must not issue mutation requests')
  await capture(trialPage, screenshotDir, screenshots, 'trial-database-redacted', onlyScenario)
  await clickMenu(trialPage, 'AI Chat', '/admin/chat')
  await trialPage.locator('.chat-page').waitFor({ state: 'visible' })
  await trialPage.locator('.empty-chat').waitFor({ state: 'visible' })
  await trialPage.locator('.trial-banner__text').waitFor({ state: 'visible' })
  assert.ok(api.requests.some((request) => request.method === 'GET' && request.path === '/api/trial/status'),
    'trial banner must reflect the completed mock trial-status request')
  await capture(trialPage, screenshotDir, screenshots, 'trial-chat-read-only', onlyScenario)
  const uploaderCount = await trialPage.locator('.file-uploader').count()
  const uploadButtonCount = await trialPage.getByRole('button', { name: /^Upload (?:Excel|file)$/ }).count()
  const expectedUploaderCount = trialUploadExpectation === 'visible' ? 1 : 0
  if (uploaderCount !== expectedUploaderCount) {
    uiAssertionFailures.push(`trial upload expectation=${trialUploadExpectation}; found .file-uploader count=${uploaderCount}`)
  }
  if (uploadButtonCount !== expectedUploaderCount) {
    uiAssertionFailures.push(`trial upload expectation=${trialUploadExpectation}; found upload button count=${uploadButtonCount}`)
  }
  const compareCount = await trialPage.getByRole('button', { name: 'Compare', exact: true }).count()
  if (compareCount !== 0) {
    uiAssertionFailures.push(`trial UI must hide compare control; found Compare button count=${compareCount}`)
  }
  await trialPage.close()
}

export { runDataSourceTrialScenarios }
