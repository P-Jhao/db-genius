import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { runBasicChatScenarios } from './s15-ui-basic-chat-scenarios.mjs'
import { runDataSourceTrialScenarios } from './s15-ui-data-source-trial-scenarios.mjs'
import { VIEWPORT } from './s15-ui-scenario-shared.mjs'

async function runUiScenarios({
  browser, url, api, screenshotDir, onlyScenario = null, trialUploadExpectation = 'visible',
}) {
  assert.ok(onlyScenario === null || [
    'database-delete-confirm',
    'trial-chat-read-only',
  ].includes(onlyScenario), `Unsupported targeted scenario: ${onlyScenario}`)
  assert.ok(['visible', 'hidden'].includes(trialUploadExpectation),
    `Unsupported trial upload expectation: ${trialUploadExpectation}`)
  await mkdir(screenshotDir, { recursive: true })
  api.reset()
  const screenshots = {}
  const pageErrors = []
  const stopCancellation = []
  const uiAssertionFailures = []
  const basicScenarioWasTargeted = await runBasicChatScenarios({
    browser, url, api, screenshotDir, screenshots, onlyScenario, pageErrors, stopCancellation,
  })
  if (basicScenarioWasTargeted) {
    return { screenshots, pageErrors, stopCancellation, uiAssertionFailures, trialUploadExpectation }
  }
  await runDataSourceTrialScenarios({
    browser, url, api, screenshotDir, screenshots, onlyScenario, trialUploadExpectation,
    uiAssertionFailures,
  })
  assert.deepEqual(pageErrors, [], 'browser pages must not report uncaught errors')
  return { screenshots, pageErrors, stopCancellation, uiAssertionFailures, trialUploadExpectation }
}

export { runUiScenarios, VIEWPORT }
