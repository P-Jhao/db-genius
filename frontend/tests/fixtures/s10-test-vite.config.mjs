import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ArcoResolver } from 'unplugin-vue-components/resolvers'
import { fileURLToPath } from 'node:url'

const frontendDir = fileURLToPath(new URL('../../', import.meta.url))
const cacheDir = process.env.SQLCHAT_TEST_VITE_CACHE_DIR
if (!cacheDir) throw new Error('SQLCHAT_TEST_VITE_CACHE_DIR must point to an isolated test cache')

export default defineConfig({
  root: frontendDir,
  envDir: false,
  cacheDir,
  define: { 'import.meta.env.VITE_API_BASE_URL': JSON.stringify('/api') },
  plugins: [
    vue(),
    AutoImport({ dts: false, resolvers: [ArcoResolver()] }),
    Components({ dts: false, resolvers: [ArcoResolver({ sideEffect: true })] }),
  ],
  resolve: { alias: { '@': fileURLToPath(new URL('../../src', import.meta.url)) } },
  optimizeDeps: {
    entries: ['tests/fixtures/s10-upload-component.html'],
    include: ['@arco-design/web-vue/es/button/style/css.js', '@arco-design/web-vue/es/tag/style/css.js'],
  },
  server: {
    proxy: {},
    fs: {
      strict: true,
      allow: [frontendDir, cacheDir],
      deny: ['**/.env', '**/.env.*', '**/*.{crt,pem,key,p12,pfx,cer,der}', '**/.npmrc', '**/.yarnrc.yml', '**/.git/**'],
    },
  },
})
