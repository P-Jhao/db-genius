import { computed } from 'vue'
import { createI18n } from 'vue-i18n'
import type { ArcoLang } from '@arco-design/web-vue/es/locale/interface'
import arcoZhCN from '@arco-design/web-vue/es/locale/lang/zh-cn'
import arcoZhTW from '@arco-design/web-vue/es/locale/lang/zh-tw'
import arcoEnUS from '@arco-design/web-vue/es/locale/lang/en-us'
import arcoEsES from '@arco-design/web-vue/es/locale/lang/es-es'
import arcoFrFR from '@arco-design/web-vue/es/locale/lang/fr-fr'
import arcoJaJP from '@arco-design/web-vue/es/locale/lang/ja-jp'
import arcoMsMY from '@arco-design/web-vue/es/locale/lang/ms-my'

import zhCN from '../locales/zh-CN'
import zhTW from '../locales/zh-TW'
import en from '../locales/en'
import es from '../locales/es'
import fr from '../locales/fr'
import ja from '../locales/ja'
import ms from '../locales/ms'
import { detectGeoLocale } from './geo'

export const SUPPORTED_LOCALES = [
  { code: 'zh-CN', nativeName: '简体中文', enName: 'Simplified Chinese' },
  { code: 'zh-TW', nativeName: '繁體中文', enName: 'Traditional Chinese' },
  { code: 'en', nativeName: 'English', enName: 'English' },
  { code: 'es', nativeName: 'Español', enName: 'Spanish' },
  { code: 'fr', nativeName: 'Français', enName: 'French' },
  { code: 'ja', nativeName: '日本語', enName: 'Japanese' },
  { code: 'ms', nativeName: 'Bahasa Melayu', enName: 'Malay' },
] as const

export type AppLocale = (typeof SUPPORTED_LOCALES)[number]['code']

const STORAGE_KEY = 'app-locale'
const FALLBACK_LOCALE: AppLocale = 'en'

const messages = {
  'zh-CN': zhCN,
  'zh-TW': zhTW,
  en,
  es,
  fr,
  ja,
  ms,
}

export function isSupportedLocale(value: unknown): value is AppLocale {
  return typeof value === 'string' && (SUPPORTED_LOCALES as readonly { code: string }[]).some((l) => l.code === value)
}

/**
 * Fuzzy-match a language tag (`zh`, `zh-HK`, `en-US`, `es-MX`, …) to a
 * supported locale. Returns `null` when nothing matches.
 */
export function matchLocale(tag: string | null | undefined): AppLocale | null {
  if (!tag) return null
  const t = tag.trim().toLowerCase()
  if (!t) return null
  if (t.startsWith('zh')) {
    return /tw|hk|mo|hant/.test(t) ? 'zh-TW' : 'zh-CN'
  }
  if (t.startsWith('en')) return 'en'
  if (t.startsWith('es')) return 'es'
  if (t.startsWith('fr')) return 'fr'
  if (t.startsWith('ja')) return 'ja'
  if (t.startsWith('ms')) return 'ms'
  return null
}

function getUrlLocale(): AppLocale | null {
  try {
    const params = new URLSearchParams(window.location.search)
    return matchLocale(params.get('lang'))
  } catch {
    return null
  }
}

/**
 * Locale pinned by a language-prefixed URL path (`/zh-CN/`, `/es/`, …).
 * The `/` root and non-landing pages (`/login`, `/admin/*`) return null.
 */
function getPathLocale(): AppLocale | null {
  try {
    const seg = window.location.pathname.split('/')[1]
    return isSupportedLocale(seg) ? seg : null
  } catch {
    return null
  }
}

function getStoredLocale(): AppLocale | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return isSupportedLocale(stored) ? stored : matchLocale(stored)
  } catch {
    return null
  }
}

function getNavigatorLocale(): AppLocale | null {
  const languages = typeof navigator !== 'undefined' ? navigator.languages ?? [navigator.language] : []
  for (const lang of languages) {
    const matched = matchLocale(lang)
    if (matched) return matched
  }
  return null
}

/**
 * Synchronously determine the initial locale:
 *   1. URL path prefix (`/zh-CN/`, …) — strongest, SEO-canonical signal
 *   2. URL query `?lang=xx` (fuzzy-matched, legacy)
 *   3. localStorage `app-locale` (only written on manual switch)
 *   4. navigator.language (fuzzy-matched)
 *   5. fallback: English
 * IP geolocation runs asynchronously after mount via `startGeoDetection()`
 * and only when none of 1–3 is present.
 */
export function detectLocale(): AppLocale {
  return getPathLocale() ?? getUrlLocale() ?? getStoredLocale() ?? getNavigatorLocale() ?? FALLBACK_LOCALE
}

/**
 * Locale preference for the root `/` page when the URL carries no language
 * signal: localStorage `app-locale` → navigator.language → null (caller
 * treats null as English).
 */
export function detectPreferredLocale(): AppLocale | null {
  return getStoredLocale() ?? getNavigatorLocale()
}

export const i18n = createI18n({
  legacy: false,
  locale: detectLocale(),
  fallbackLocale: FALLBACK_LOCALE,
  messages,
})

export function getCurrentLocale(): AppLocale {
  const value = i18n.global.locale.value
  return isSupportedLocale(value) ? value : FALLBACK_LOCALE
}

/** Apply a locale: vue-i18n + `<html lang>` + Arco locale react via computed. */
export function setLocale(locale: AppLocale): void {
  i18n.global.locale.value = locale
  document.documentElement.lang = locale
}

/**
 * Manual language switch: apply the locale, persist the choice, and drop the
 * `lang` query param so the URL no longer pins the language.
 */
export function applyUserChoice(locale: AppLocale): void {
  persistLocaleChoice(locale)
  try {
    const url = new URL(window.location.href)
    if (url.searchParams.has('lang')) {
      url.searchParams.delete('lang')
      window.history.replaceState(window.history.state, '', url.toString())
    }
  } catch {
    // non-critical — ignore
  }
}

/**
 * Apply + persist an explicit locale choice without touching the URL.
 * Safe to call from navigation guards (unlike `applyUserChoice`, which
 * rewrites the address bar via history.replaceState).
 */
export function persistLocaleChoice(locale: AppLocale): void {
  setLocale(locale)
  try {
    localStorage.setItem(STORAGE_KEY, locale)
  } catch {
    // storage unavailable — ignore silently
  }
}

/**
 * Set when the locale was driven by a language-prefixed URL (or a legacy
 * `?lang=` redirect). Counts as an explicit choice so IP geolocation never
 * overrides the page the user is actually on.
 */
let urlDrivenChoice = false

export function markUrlDriven(): void {
  urlDrivenChoice = true
}

function hasExplicitChoice(): boolean {
  return urlDrivenChoice || getUrlLocale() !== null || getStoredLocale() !== null || getPathLocale() !== null
}

/**
 * Asynchronous IP geolocation detection. Runs only when the user has no
 * explicit choice (URL param, language-prefixed URL, or stored preference).
 *
 * When a router is passed and the user is still on the root landing page
 * (`/`), a detected non-English locale navigates to the language-prefixed
 * URL (`/<locale>/`) via `router.replace` — keeping one URL per language for
 * SEO. On any other page the locale is applied in place (previous behavior).
 * Never throws and never blocks startup.
 */
export function startGeoDetection(router?: {
  currentRoute: { value: { name?: unknown; path: string } }
  replace: (location: string) => unknown
}): void {
  if (hasExplicitChoice()) return
  detectGeoLocale()
    .then((geoLocale) => {
      // The user may have switched manually while the request was in flight.
      if (!geoLocale || hasExplicitChoice()) return
      if (geoLocale === getCurrentLocale()) return
      const current = router?.currentRoute.value
      if (router && current?.name === 'landing' && current.path === '/') {
        // Only redirect while the user is still on the root landing page.
        router.replace(`/${geoLocale}/`)
      } else {
        setLocale(geoLocale)
      }
    })
    .catch(() => {
      // silent fallback — the app keeps the navigator/fallback locale
    })
}

/**
 * Arco Design Vue component-locale mapping. All seven languages have an
 * official Arco lang pack (verified in
 * `node_modules/@arco-design/web-vue/es/locale/lang/`); unknown values fall
 * back to en-US.
 */
const arcoLocaleMap: Record<AppLocale, ArcoLang> = {
  'zh-CN': arcoZhCN,
  'zh-TW': arcoZhTW,
  en: arcoEnUS,
  es: arcoEsES,
  fr: arcoFrFR,
  ja: arcoJaJP,
  ms: arcoMsMY,
}

/** Reactive Arco locale for `<a-config-provider :locale="...">` in App.vue. */
export const currentArcoLocale = computed<ArcoLang>(
  () => arcoLocaleMap[getCurrentLocale()] ?? arcoEnUS,
)

/**
 * Sync document meta from `landing.meta.*` keys: title, meta description /
 * keywords, Open Graph (title / description / locale / image:alt) and the
 * matching Twitter Card fields. Missing meta tags are created on the fly;
 * keys that don't exist are silently skipped.
 */
function setMeta(attr: 'name' | 'property', key: string, content: string): void {
  let el = document.head.querySelector(`meta[${attr}="${key}"]`)
  if (!el) {
    el = document.createElement('meta')
    el.setAttribute(attr, key)
    document.head.appendChild(el)
  }
  el.setAttribute('content', content)
}

export function updateDocumentMeta(): void {
  try {
    const { t, te } = i18n.global
    if (te('landing.meta.title')) {
      document.title = t('landing.meta.title')
    }
    if (te('landing.meta.description')) {
      setMeta('name', 'description', t('landing.meta.description'))
    }
    if (te('landing.meta.keywords')) {
      setMeta('name', 'keywords', t('landing.meta.keywords'))
    }
    if (te('landing.meta.ogTitle')) {
      setMeta('property', 'og:title', t('landing.meta.ogTitle'))
      setMeta('name', 'twitter:title', t('landing.meta.ogTitle'))
    }
    if (te('landing.meta.ogDescription')) {
      setMeta('property', 'og:description', t('landing.meta.ogDescription'))
      setMeta('name', 'twitter:description', t('landing.meta.ogDescription'))
    }
    if (te('landing.meta.ogLocale')) {
      setMeta('property', 'og:locale', t('landing.meta.ogLocale'))
    }
    if (te('landing.meta.ogImageAlt')) {
      setMeta('property', 'og:image:alt', t('landing.meta.ogImageAlt'))
      setMeta('name', 'twitter:image:alt', t('landing.meta.ogImageAlt'))
    }
  } catch {
    // keys not present yet — silently skip
  }
}
