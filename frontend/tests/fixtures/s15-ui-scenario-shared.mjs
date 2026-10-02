import assert from 'node:assert/strict'
import { join } from 'node:path'

const VIEWPORT = { width: 1440, height: 1000 }
const USER = { username: 's15-reviewer', nickname: 'S15 Reviewer', role: 'admin' }

const VISUAL_STABILITY_TIMEOUT_MS = 5000
const REQUIRED_STABLE_FRAMES = 3
const RECT_EPSILON_PX = 0.25
const OPACITY_EPSILON = 0.001

async function waitForVisualStability(locator, label) {
  await locator.waitFor({ state: 'attached', timeout: VISUAL_STABILITY_TIMEOUT_MS })
  const result = await locator.evaluate(async (element, options) => {
    const deadline = performance.now() + options.timeoutMs
    let previousRect = null
    let stableFrames = 0
    let lastSample = null

    const sample = () => {
      const rect = element.getBoundingClientRect()
      const viewport = { width: window.innerWidth, height: window.innerHeight }
      const styles = []
      const runningAnimations = []
      for (let node = element; node instanceof Element; node = node.parentElement) {
        const style = getComputedStyle(node)
        styles.push({
          opacity: Number(style.opacity),
          transform: style.transform,
          backgroundColor: style.backgroundColor,
          visibility: style.visibility,
          display: style.display,
        })
        for (const animation of node.getAnimations()) {
          if (animation.playState === 'running' || animation.pending) {
            runningAnimations.push({
              name: animation.animationName ?? animation.constructor.name,
              playState: animation.playState,
            })
          }
        }
      }
      const inViewport = rect.left >= 0 && rect.top >= 0 &&
        rect.right <= viewport.width && rect.bottom <= viewport.height
      const center = { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }
      const hit = document.elementFromPoint(center.x, center.y)
      const unobscured = hit !== null && element.contains(hit)
      const fullyOpaque = styles.every((style) => style.opacity >= 1 - options.opacityEpsilon)
      const rendered = rect.width > 0 && rect.height > 0 &&
        styles.every((style) => style.display !== 'none' && style.visibility !== 'hidden')
      const ready = inViewport && unobscured && fullyOpaque && rendered && runningAnimations.length === 0
      return {
        ready,
        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
        viewport,
        center,
        hit: hit ? `${hit.tagName.toLowerCase()}.${String(hit.className).replace(/\s+/g, '.')}` : null,
        inViewport,
        unobscured,
        fullyOpaque,
        rendered,
        runningAnimations,
        styles,
      }
    }

    const sameRect = (left, right) => left !== null &&
      Math.abs(left.x - right.x) <= options.rectEpsilonPx &&
      Math.abs(left.y - right.y) <= options.rectEpsilonPx &&
      Math.abs(left.width - right.width) <= options.rectEpsilonPx &&
      Math.abs(left.height - right.height) <= options.rectEpsilonPx

    while (performance.now() < deadline) {
      await new Promise((resolve) => requestAnimationFrame(resolve))
      lastSample = sample()
      if (lastSample.ready && sameRect(previousRect, lastSample.rect)) {
        stableFrames += 1
      } else {
        stableFrames = 0
      }
      if (stableFrames >= options.requiredStableFrames) {
        return { ready: true, stableFrames, sample: lastSample }
      }
      previousRect = lastSample.rect
    }
    return { ready: false, stableFrames, sample: lastSample }
  }, {
    timeoutMs: VISUAL_STABILITY_TIMEOUT_MS,
    requiredStableFrames: REQUIRED_STABLE_FRAMES,
    rectEpsilonPx: RECT_EPSILON_PX,
    opacityEpsilon: OPACITY_EPSILON,
  })

  if (!result.ready) {
    throw new Error(`${label} did not become visible, unobscured, and stable within ${VISUAL_STABILITY_TIMEOUT_MS}ms: ${JSON.stringify(result)}`)
  }
}

async function makePage(browser, token = null) {
  const page = await browser.newPage({ viewport: VIEWPORT, locale: 'en-US', timezoneId: 'UTC' })
  await page.addInitScript(({ authToken, user }) => {
    localStorage.setItem('app-locale', 'en')
    if (authToken !== null) {
      localStorage.setItem('token', authToken)
      localStorage.setItem('userInfo', JSON.stringify({ ...user, token: authToken }))
    }
  }, { authToken: token, user: USER })
  return page
}

async function capture(page, screenshotDir, screenshots, name, onlyScenario, fullPage = true) {
  if (onlyScenario !== null && onlyScenario !== name) return
  if (name.startsWith('chat-')) {
    const sendButton = page.getByRole('button', { name: 'Send', exact: true })
    const input = page.locator('.chat-input-area textarea')
    await sendButton.waitFor({ state: 'visible' })
    await page.getByRole('button', { name: 'Stop', exact: true }).waitFor({ state: 'detached' })
    assert.equal(await page.getByRole('button', { name: 'Stop', exact: true }).count(), 0,
      `${name}: Stop must disappear after the stream reaches a terminal state`)
    assert.equal(await input.isEnabled(), true, `${name}: chat input must be available after the stream ends`)
    const streamingIndicator = page.locator('.streaming-indicator')
    try {
      await streamingIndicator.waitFor({ state: 'detached', timeout: 5000 })
    } catch (error) {
      const failureName = `${name}-terminal-failure`
      const failurePath = join(screenshotDir, `${failureName}.png`)
      await page.screenshot({ path: failurePath, fullPage, animations: 'disabled' })
      screenshots[failureName] = failurePath
      throw new Error(`${name}: streaming indicator remained visible after terminal-state wait; evidence=${failurePath}; ${String(error)}`)
    }
    assert.equal(await streamingIndicator.count(), 0,
      `${name}: streaming indicator must be cleared before screenshot capture`)
  }
  if (name === 'trial-chat-read-only') {
    await waitForVisualStability(page.locator('.chat-page'), 'trial chat page')
    await waitForVisualStability(page.locator('.empty-chat'), 'trial chat empty state')
    await waitForVisualStability(page.locator('.trial-banner__text'), 'trial banner')
  }
  await page.evaluate(() => document.fonts.ready)
  const screenshotPath = join(screenshotDir, `${name}.png`)
  await page.screenshot({ path: screenshotPath, fullPage, animations: 'disabled' })
  screenshots[name] = screenshotPath
}

async function clickMenu(page, label, route) {
  const item = page.locator('.desktop-sider .arco-menu-item').filter({ hasText: label })
  const beforeClick = await item.evaluateAll((items) => items.map((element) => ({
    text: element.textContent?.trim(),
    key: element.getAttribute('data-key'),
    visible: element.getBoundingClientRect().width > 0,
  })))
  await item.click()
  try {
    await page.waitForURL(`**${route}`, { timeout: 3000 })
  } catch (error) {
    throw new Error(`Menu click ${label} expected ${route}, got ${page.url()}, items=${JSON.stringify(beforeClick)}: ${String(error)}`)
  }
}

export { capture, clickMenu, makePage, VIEWPORT, waitForVisualStability }
