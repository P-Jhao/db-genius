import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { existsSync } from 'node:fs'
import { mkdtemp } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

export async function startFrontend() {
  const socket = createServer()
  socket.listen(0, '127.0.0.1')
  await once(socket, 'listening')
  const address = socket.address()
  if (address === null || typeof address === 'string') throw new Error('Missing fixture port')
  await new Promise((resolve) => socket.close(resolve))
  const url = `http://127.0.0.1:${address.port}`
  const cacheDir = await mkdtemp(join(tmpdir(), 'sqlchat-terminal-'))
  const vite = spawn(process.execPath, [
    fileURLToPath(new URL('../../node_modules/vite/bin/vite.js', import.meta.url)),
    '--config', 'tests/fixtures/chat-terminal-vite.config.mjs',
    '--host', '127.0.0.1', '--port', String(address.port), '--strictPort',
  ], {
    cwd: fileURLToPath(new URL('../../', import.meta.url)),
    env: { ...process.env, SQLCHAT_TERMINAL_CACHE: cacheDir, VITE_API_BASE_URL: '/api' },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  let output = ''
  vite.stdout.on('data', (chunk) => { output += chunk.toString() })
  vite.stderr.on('data', (chunk) => { output += chunk.toString() })
  try {
    for (let attempt = 0; attempt < 150; attempt++) {
      if (vite.exitCode !== null) throw new Error(`Fixture exited: ${output}`)
      try {
        if ((await fetch(url)).ok) return { url, vite }
      } catch { /* server is starting */ }
      await new Promise((resolve) => setTimeout(resolve, 100))
    }
    throw new Error(`Fixture startup timeout: ${output}`)
  } catch (error) {
    await stopFrontend(vite)
    throw error
  }
}

export function launchBrowser() {
  return chromium.launch(existsSync(chromium.executablePath())
    ? { headless: true } : { headless: true, channel: 'chrome' })
}

export async function stopFrontend(vite, browser) {
  try { await browser?.close() } finally {
    if (vite.exitCode === null) {
      const exited = once(vite, 'exit')
      vite.kill()
      await exited
    }
  }
}

export const success = (data) => ({ code: 200, message: 'success', data })
