import { mergeConfig } from 'vite'
import { readdirSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import appConfig from '../../vite.config.ts'

const cacheDir = process.env.SQLCHAT_TERMINAL_CACHE
if (!cacheDir) throw new Error('SQLCHAT_TERMINAL_CACHE is required')
const arcoDir = fileURLToPath(new URL('../../node_modules/@arco-design/web-vue/es/', import.meta.url))
const styles = readdirSync(arcoDir).filter((name) => existsSync(`${arcoDir}/${name}/style/css.js`))
  .map((name) => `@arco-design/web-vue/es/${name}/style/css.js`)

export default mergeConfig(appConfig, {
  cacheDir,
  optimizeDeps: {
    noDiscovery: true,
    include: ['vue', 'pinia', 'vue-router', 'vue-i18n', 'axios', 'marked', 'dompurify',
      '@vueuse/core', '@microsoft/fetch-event-source', '@arco-design/web-vue',
      '@arco-design/web-vue/es/icon', ...styles],
  },
})
