import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '../stores/user'
import {
  detectPreferredLocale,
  isSupportedLocale,
  markUrlDriven,
  matchLocale,
  persistLocaleChoice,
  setLocale,
} from '../i18n'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'landing',
      component: () => import('../views/landing/LandingPage.vue'),
    },
    {
      // Language-prefixed landing pages (English stays at `/`).
      path: '/:locale(zh-CN|zh-TW|es|fr|ja|ms)',
      name: 'landing-locale',
      component: () => import('../views/landing/LandingPage.vue'),
    },
    {
      // `/en` and `/en/` must not duplicate the root page.
      path: '/en',
      redirect: '/',
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/login/LoginPage.vue'),
    },
    {
      path: '/admin',
      component: () => import('../views/admin/AdminLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        {
          path: '',
          redirect: '/admin/chat',
        },
        {
          path: 'chat',
          name: 'chat',
          component: () => import('../views/admin/ChatPage.vue'),
        },
        {
          path: 'db-config',
          name: 'db-config',
          component: () => import('../views/admin/DbConfigPage.vue'),
        },
        {
          path: 'model-config',
          name: 'model-config',
          component: () => import('../views/admin/ModelConfigPage.vue'),
        },
        {
          path: 'conversations',
          name: 'conversations',
          component: () => import('../views/admin/ConversationsPage.vue'),
        },
      ],
    },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})

// Locale guard: resolves the language for landing URLs before rendering.
// URL signals (path prefix, legacy ?lang=) count as explicit choices so IP
// geolocation never overrides them.
router.beforeEach((to) => {
  if (to.name === 'landing-locale') {
    const locale = Array.isArray(to.params.locale) ? to.params.locale[0] : to.params.locale
    if (isSupportedLocale(locale)) {
      setLocale(locale)
      markUrlDriven()
    }
    return
  }
  if (to.name === 'landing') {
    // Legacy `?lang=xx` links: treat as an explicit choice and move the
    // language into the URL path.
    const langParam = matchLocale(typeof to.query.lang === 'string' ? to.query.lang : null)
    if (langParam) {
      persistLocaleChoice(langParam)
      markUrlDriven()
      return { path: langParam === 'en' ? '/' : `/${langParam}/`, replace: true }
    }
    // No language signal in the URL: stored choice → navigator → English.
    const preferred = detectPreferredLocale()
    if (preferred && preferred !== 'en') {
      return { path: `/${preferred}/`, replace: true }
    }
    setLocale('en')
  }
})

router.beforeEach((to) => {
  const requiresAuth = to.matched.some((record) => record.meta.requiresAuth)
  if (requiresAuth) {
    const userStore = useUserStore()
    if (!userStore.isLoggedIn) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
  }
})

export default router
