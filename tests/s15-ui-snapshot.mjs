import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import {
  cpSync, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync,
} from 'node:fs'
import { join, relative, sep } from 'node:path'

function walkFiles(root) {
  const files = []
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, entry.name)
    if (entry.isDirectory()) files.push(...walkFiles(path))
    else files.push(path)
  }
  return files
}

function scanForCredentialMaterial(root) {
  const forbidden = /(?:sk-[A-Za-z0-9]{24,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)/
  for (const path of walkFiles(root)) {
    if (/\.(png|jpe?g|gif|svg|ico|webp|woff2?)$/i.test(path)) continue
    if (forbidden.test(readFileSync(path, 'utf8'))) throw new Error(`Credential-like content found in ${path}`)
  }
}

function copyOriginalSnapshot(originalSource, snapshotPath) {
  if (!existsSync(join(originalSource, 'src')) || !existsSync(join(originalSource, 'package.json'))) {
    throw new Error(`Original frontend source is unavailable: ${originalSource}`)
  }
  mkdirSync(snapshotPath, { recursive: true })
  const excludedParts = new Set(['.git', 'node_modules', 'dist', 'coverage', '__pycache__'])
  const filter = (sourcePath) => {
    const name = sourcePath.split(/[\\/]/).at(-1) ?? ''
    if (name === '.env' || name.startsWith('.env.') || /\.(pem|p12|pfx|key)$/i.test(name)) return false
    return !sourcePath.split(/[\\/]/).some((part) => excludedParts.has(part))
  }
  for (const directory of ['src', 'public']) {
    const source = join(originalSource, directory)
    if (existsSync(source)) cpSync(source, join(snapshotPath, directory), { recursive: true, filter })
  }
  const files = [
    'index.html', 'package.json', 'package-lock.json', 'vite.config.ts',
    'tsconfig.json', 'tsconfig.app.json', 'tsconfig.node.json',
    'components.d.ts', 'auto-imports.d.ts',
  ]
  for (const name of files) {
    const source = join(originalSource, name)
    if (existsSync(source) && filter(source)) cpSync(source, join(snapshotPath, name))
  }
  const appTsconfig = join(snapshotPath, 'tsconfig.app.json')
  if (existsSync(appTsconfig)) {
    const config = JSON.parse(readFileSync(appTsconfig, 'utf8'))
    config.extends = './s15-vite-tsconfig.json'
    writeFileSync(appTsconfig, `${JSON.stringify(config, null, 2)}\n`, 'utf8')
    writeFileSync(join(snapshotPath, 's15-vite-tsconfig.json'), `${JSON.stringify({
      compilerOptions: {
        target: 'ESNext', module: 'ESNext', moduleResolution: 'bundler', jsx: 'preserve',
        strict: true, skipLibCheck: true, types: ['vite/client'],
      },
    }, null, 2)}\n`, 'utf8')
  }
  for (const name of ['.env', '.git', 'node_modules', 'dist']) {
    assert.equal(existsSync(join(snapshotPath, name)), false, `snapshot must exclude ${name}`)
  }
  scanForCredentialMaterial(snapshotPath)
}

function fingerprint(root) {
  const hash = createHash('sha256')
  for (const path of walkFiles(root).sort()) {
    hash.update(relative(root, path).split(sep).join('/'))
    hash.update(readFileSync(path))
  }
  return hash.digest('hex')
}

function sha256File(path) {
  return createHash('sha256').update(readFileSync(path)).digest('hex')
}

export { copyOriginalSnapshot, fingerprint, sha256File }
