import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ArcoResolver } from 'unplugin-vue-components/resolvers'
import { resolve } from 'node:path'

const appRoot = process.env.S15_UI_ROOT
const dependencyRoot = process.env.S15_UI_DEPS
const cacheDir = process.env.S15_UI_CACHE_DIR
if (!appRoot) throw new Error('S15_UI_ROOT must point to a UI source snapshot')
if (!dependencyRoot) throw new Error('S15_UI_DEPS must point to the existing pnpm frontend install')
if (!cacheDir) throw new Error('S15_UI_CACHE_DIR must point to an isolated per-run Vite cache')

const runtimePackages = [
  '@arco-design/web-vue', '@microsoft/fetch-event-source', '@vueuse/core',
  'axios', 'dompurify', 'marked', 'pinia', 'vue', 'vue-i18n', 'vue-router',
]
const packageAliases = runtimePackages.map((name) => ({
  find: new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?=/|$)`),
  replacement: resolve(dependencyRoot, 'node_modules', ...name.split('/')),
}))

export default defineConfig({
  root: appRoot,
  cacheDir,
  tsconfig: resolve(appRoot, 'tsconfig.app.json'),
  plugins: [
    vue(),
    AutoImport({ resolvers: [ArcoResolver()] }),
    Components({ resolvers: [ArcoResolver({ sideEffect: true })] }),
  ],
  resolve: {
    alias: [...packageAliases, { find: '@', replacement: resolve(appRoot, 'src') }],
    dedupe: ['vue', 'vue-router', 'pinia'],
  },
  optimizeDeps: { include: ['@arco-design/web-vue'] },
  server: {
    host: '127.0.0.1',
    cors: true,
    fs: {
      allow: [appRoot, dependencyRoot],
      deny: [
        '**/.env', '**/.env.*', '**/*.{crt,pem,key,p12,pfx,cer,der}',
        '**/.npmrc', '**/.yarnrc.yml', '**/.git', '**/.git/**',
      ],
    },
  },
})
