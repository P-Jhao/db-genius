import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { createServer } from 'node:net'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { randomUUID } from 'node:crypto'
import {
  existsSync, mkdirSync, readFileSync, writeFileSync,
} from 'node:fs'
import { join, resolve, sep } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { buildApiFixture } from '../frontend/tests/fixtures/s15-ui-api.mjs'
import { runUiScenarios, VIEWPORT } from '../frontend/tests/fixtures/s15-ui-scenarios.mjs'
import { copyOriginalSnapshot, fingerprint, sha256File } from './s15-ui-snapshot.mjs'
import { compareScreenshots } from './s15-ui-visual-diff.mjs'

const repoRoot = fileURLToPath(new URL('..', import.meta.url))
const frontendDir = join(repoRoot, 'frontend')
const pnpmLockfile = join(frontendDir, 'pnpm-lock.yaml')
const originalSource = process.env.DB_GENIUS_FRONTEND_ROOT ??
  resolve(repoRoot, '..', 'db-genius', 'db-genius-web-master')
const acceptanceDir = join(repoRoot, '.git', 'acceptance')
const viteConfig = join(frontendDir, 'tests', 'fixtures', 's15-vite.config.mjs')
const viteBin = join(frontendDir, 'node_modules', 'vite', 'bin', 'vite.js')
const chromium = createRequire(join(frontendDir, 'package.json'))('playwright').chromium

async function freePort() {
  const server = createServer()
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  const address = server.address()
  if (typeof address !== 'object' || address === null) throw new Error('No free test port')
  server.close()
  await once(server, 'close')
  return address.port
}

async function startVite(appRoot, apiUrl) {
  const port = await freePort()
  const url = `http://127.0.0.1:${port}`
  let output = ''
  const vite = spawn(process.execPath, [viteBin, '--config', viteConfig, '--host', '127.0.0.1',
    '--port', String(port), '--strictPort'], {
    cwd: frontendDir,
    env: {
      ...process.env,
      VITE_API_BASE_URL: apiUrl,
      S15_UI_ROOT: appRoot,
      S15_UI_DEPS: frontendDir,
      S15_UI_CACHE_DIR: join(tmpdir(), 'sqlchat-s15-vite-cache', randomUUID()),
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  vite.stdout.setEncoding('utf8').on('data', (chunk) => { output += chunk })
  vite.stderr.setEncoding('utf8').on('data', (chunk) => { output += chunk })
  for (let attempt = 0; attempt < 150; attempt++) {
    if (vite.exitCode !== null) throw new Error(`Vite exited with ${vite.exitCode}:\n${output}`)
    try {
      if ((await fetch(url)).ok) return { vite, url, output: () => output }
    } catch { /* wait for Vite startup */ }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 100))
  }
  vite.kill()
  throw new Error(`Vite did not start within 15 seconds:\n${output}`)
}

async function stopVite(vite) {
  if (vite && vite.exitCode === null) {
    const exited = once(vite, 'exit')
    vite.kill()
    await exited
  }
}

async function warmViteOptimizer(browser, server) {
  const page = await browser.newPage({ viewport: VIEWPORT, locale: 'en-US', timezoneId: 'UTC' })
  try {
    await page.addInitScript(() => {
      localStorage.setItem('app-locale', 'en')
      localStorage.setItem('token', 's15-warmup-token')
      localStorage.setItem('userInfo', JSON.stringify({
        token: 's15-warmup-token', username: 's15-reviewer', nickname: 'S15 Reviewer', role: 'admin',
      }))
    })
    const routes = [
      ['/', '.landing-page'],
      ['/login', '.login-page'],
      ['/admin/chat', '.chat-page'],
      ['/admin/db-config', '.page-container'],
      ['/admin/model-config', '.page-container'],
      ['/admin/conversations', '.page-container'],
    ]
    for (const [path, selector] of routes) {
      await page.goto(`${server.url}${path}`)
      await page.locator(selector).waitFor({ timeout: 15000 })
    }
    await page.waitForTimeout(20000)
    await page.locator('.page-container').waitFor({ timeout: 15000 })
  } finally {
    await page.close()
  }
}

test('S15 T01: compare original UI with candidate using one Chrome and a fixed API fixture', { timeout: 300000 }, async () => {
  const onlyScenario = process.env.S15_UI_ONLY_SCENARIO ?? null
  const candidateTrialUploadExpectation = process.env.S15_UI_CANDIDATE_TRIAL_UPLOAD ?? 'visible'
  if (!['visible', 'hidden'].includes(candidateTrialUploadExpectation)) {
    throw new Error(`Unsupported candidate trial-upload expectation: ${candidateTrialUploadExpectation}`)
  }
  if (onlyScenario !== null && !['database-delete-confirm', 'trial-chat-read-only'].includes(onlyScenario)) {
    throw new Error(`Unsupported S15 targeted scenario: ${onlyScenario}`)
  }
  mkdirSync(acceptanceDir, { recursive: true })
  const runId = randomUUID()
  const originalSnapshot = join(tmpdir(), 'sqlchat-s15-ui-original', runId)
  const artifactDir = join(acceptanceDir, `s15-ui-${runId}`)
  mkdirSync(artifactDir, { recursive: true })
  if (onlyScenario !== null) {
    console.log(`S15_UI_RUN=${runId}`)
    console.log(`S15_UI_ARTIFACT_DIR=${artifactDir}`)
  }
  copyOriginalSnapshot(originalSource, originalSnapshot)

  const api = buildApiFixture()
  const { url: apiUrl } = await api.start()
  let originalServer
  let candidateServer
  let browser
  try {
      originalServer = await startVite(originalSnapshot, apiUrl)
      candidateServer = await startVite(frontendDir, apiUrl)
      for (const server of [originalServer, candidateServer]) {
        const gitHead = join(repoRoot, '.git', 'HEAD').split(sep).join('/')
        const response = await fetch(`${server.url}/@fs/${gitHead}`)
        assert.equal(response.status, 403, 'Vite must deny access to Git metadata')
      }
      browser = await chromium.launch(existsSync(chromium.executablePath())
      ? { headless: true }
      : { channel: 'chrome', headless: true })
      await warmViteOptimizer(browser, originalServer)
      await warmViteOptimizer(browser, candidateServer)

      let original
    try {
    original = await runUiScenarios({
      browser, url: originalServer.url, api, screenshotDir: join(artifactDir, 'original'),
      onlyScenario, trialUploadExpectation: 'visible',
      })
    } catch (error) {
      throw new Error(`Original UI scenario failed: ${String(error)}\nVite output:\n${originalServer.output()}`)
    }
    let candidate
    try {
    candidate = await runUiScenarios({
      browser, url: candidateServer.url, api, screenshotDir: join(artifactDir, 'candidate'),
      onlyScenario, trialUploadExpectation: candidateTrialUploadExpectation,
      })
    } catch (error) {
      if (onlyScenario !== null && original.screenshots[onlyScenario]) {
        const candidatePath = join(artifactDir, 'candidate', `${onlyScenario}.png`)
        if (existsSync(candidatePath)) {
          const candidateScreenshots = { [onlyScenario]: candidatePath }
          const originalScreenshots = { [onlyScenario]: original.screenshots[onlyScenario] }
          const visualDiff = await compareScreenshots(browser, originalScreenshots, candidateScreenshots, [onlyScenario])
          const failureReport = {
            runId,
            generatedAt: new Date().toISOString(),
            result: 'targeted screenshot captured; candidate UI assertion failed',
            onlyScenario,
            failure: String(error),
            originalSource,
            originalSnapshot,
            originalSha256: fingerprint(originalSnapshot),
            candidateSource: frontendDir,
            candidateSha256: fingerprint(join(frontendDir, 'src')),
            screenshots: { original: originalScreenshots, candidate: candidateScreenshots },
            visualDiff,
            pageErrors: { original: original.pageErrors, candidate: null },
            apiEvidence: 'same in-process HTTP fixture for both apps; not a live FastAPI integration',
          }
          const reportPath = join(artifactDir, 'targeted-failure-report.json')
          writeFileSync(reportPath, `${JSON.stringify(failureReport, null, 2)}\n`, 'utf8')
          console.log(`S15_UI_FAILURE_REPORT=${reportPath}`)
        }
      }
      throw new Error(`Candidate UI scenario failed: ${String(error)}\nAPI requests: ${JSON.stringify(api.requests)}\nVite output:\n${candidateServer.output()}`)
    }
    const names = Object.keys(original.screenshots).sort()
    assert.deepEqual(Object.keys(candidate.screenshots).sort(), names)
    const visualDiff = await compareScreenshots(browser, original.screenshots, candidate.screenshots, names)
    const uiAssertionFailures = {
      original: original.uiAssertionFailures,
      candidate: candidate.uiAssertionFailures,
    }
    const hasUiAssertionFailures = Object.values(uiAssertionFailures).some((failures) => failures.length > 0)
    const report = {
      runId,
      generatedAt: new Date().toISOString(),
      result: hasUiAssertionFailures
        ? 'screenshots captured; one or more trial UI restriction assertions failed'
        : onlyScenario === null
        ? 'browser fixture scenarios passed; visual differences require reviewer interpretation'
        : 'targeted browser fixture scenario passed; visual differences require reviewer interpretation',
      onlyScenario,
      browser: browser.version(),
      viewport: VIEWPORT,
      language: 'en',
      apiEvidence: 'same in-process HTTP fixture for both apps; not a live FastAPI integration',
      originalSource,
      originalSnapshot,
      originalSha256: fingerprint(originalSnapshot),
      candidateSource: frontendDir,
      candidateSha256: fingerprint(join(frontendDir, 'src')),
      dependencyRuntime: {
        packageManager: JSON.parse(readFileSync(join(frontendDir, 'package.json'), 'utf8')).packageManager,
        nodeVersion: process.version,
        lockfile: pnpmLockfile,
        lockSha256: sha256File(pnpmLockfile),
        sharedByOriginalAndCandidate: true,
      },
      screenshots: { original: original.screenshots, candidate: candidate.screenshots },
      terminalChatScreenshots: names.filter((name) => name.startsWith('chat-')),
      visualDiff,
      uiAssertionFailures,
      trialUploadExpectation: {
        original: original.trialUploadExpectation,
        candidate: candidate.trialUploadExpectation,
      },
      stopCancellation: { original: original.stopCancellation, candidate: candidate.stopCancellation },
      interactions: onlyScenario === 'database-delete-confirm' ? [
        'login form POST fixture succeeded and entered /admin/chat',
        'exact “Logged in successfully” notification appeared after login and detached before the database-delete screenshot',
        'Database Config page opened and the database delete confirmation was opened',
      ] : onlyScenario === 'trial-chat-read-only' ? [
        'trial chat screenshot waited for .chat-page, .empty-chat, and the completed mock trial-status banner',
        `trial upload visibility was asserted as ${candidateTrialUploadExpectation} for candidate and visible for original`,
      ] : [
        'landing Sign In click opened /login',
        'login form POST fixture succeeded and entered /admin/chat',
        'sidebar clicks opened chat, database, model, and history pages',
        'database and model create dialogs and database delete confirmation opened',
        'history drawer opened and Continue Chat replayed fixture messages',
      'clarification option sent confirmedIntent=sql_query and rendered step/summary events',
      'Stop click cancelled the exact in-flight chat POST with net::ERR_ABORTED',
      'chat screenshots require Send visible, Stop removed, an enabled textarea, and no streaming indicator',
        'empty database list and API error state rendered',
        'trial database fixture returned redacted values; restricted upload/compare controls stayed hidden',
      ],
      pageErrors: { original: original.pageErrors, candidate: candidate.pageErrors },
    }
    const reportPath = join(artifactDir, 'report.json')
    writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8')
    console.log(`S15_UI_RUN=${runId}`)
    console.log(`S15_UI_REPORT=${reportPath}`)
    console.log(`S15_UI_SCREENSHOTS=${names.length * 2}`)
    console.log(`S15_UI_DIFF=${JSON.stringify(visualDiff)}`)
    console.log(`S15_UI_ASSERTION_FAILURES=${JSON.stringify(uiAssertionFailures)}`)
    assert.deepEqual(uiAssertionFailures, { original: [], candidate: [] },
      'trial UI restriction assertions must pass on both original and candidate')
  } finally {
    await browser?.close()
    await stopVite(candidateServer?.vite)
    await stopVite(originalServer?.vite)
    await api.close()
  }
})
