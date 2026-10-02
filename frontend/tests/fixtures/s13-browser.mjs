import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { mkdtemp } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { existsSync } from 'node:fs'
import { chromium } from 'playwright'

const frontendDir = fileURLToPath(new URL('../../', import.meta.url))
const viteBin = fileURLToPath(new URL('../../node_modules/vite/bin/vite.js', import.meta.url))
const viteConfig = 'tests/fixtures/s13-test-vite.config.mjs'

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

export async function startS13Frontend() {
  const port = await freePort()
  const url = `http://127.0.0.1:${port}`
  const cacheDir = await mkdtemp(join(tmpdir(), 'sqlchat-s13-vite-cache-'))
  const vite = spawn(process.execPath, [viteBin, '--config', viteConfig, '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
    cwd: frontendDir,
    stdio: 'ignore',
    env: {
      ...process.env,
      VITE_API_BASE_URL: '/api',
      SQLCHAT_TEST_VITE_CACHE_DIR: cacheDir,
    },
  })
  for (let attempt = 0; attempt < 100; attempt++) {
    if (vite.exitCode !== null) throw new Error(`Vite exited with ${vite.exitCode}`)
    try {
      if ((await fetch(url)).ok) return { url, vite, cacheDir }
    } catch {
      // Vite is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  vite.kill()
  throw new Error('Vite did not start within 10 seconds')
}

export async function launchS13Browser() {
  return chromium.launch(existsSync(chromium.executablePath())
    ? { headless: true }
    : { channel: 'chrome', headless: true })
}

export async function stopS13Frontend(vite, browser) {
  await browser?.close()
  if (vite.exitCode === null) {
    const exited = once(vite, 'exit')
    vite.kill()
    await exited
  }
}

export function success(data) {
  return { code: 200, message: 'success', data }
}
