import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ArcoVue from '@arco-design/web-vue'
import ArcoVueIcon from '@arco-design/web-vue/es/icon'
import '@arco-design/web-vue/dist/arco.css'
import App from './App.vue'
import router from './router'
import { i18n, setLocale, detectLocale, startGeoDetection } from './i18n'
import './styles/global.scss'

// Determine the initial locale synchronously (URL ?lang → localStorage →
// navigator → fallback 'en') before the app mounts.
setLocale(detectLocale())

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(i18n)
app.use(ArcoVue)
app.use(ArcoVueIcon)
app.mount('#app')

// IP geolocation detection runs asynchronously after mount; it only applies
// when the user has no explicit choice and never blocks startup. On the root
// landing page a non-English result redirects to the language-prefixed URL.
startGeoDetection(router)
