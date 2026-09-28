import { SUPPORTED_LOCALES } from './index'
import type { AppLocale } from './index'

export const SEO_BASE_URL = 'https://db-genius.com'

/**
 * Canonical URL for a locale's landing page. English lives at the root and
 * doubles as the hreflang `x-default` target.
 */
export function localeUrl(locale: AppLocale): string {
  return locale === 'en' ? `${SEO_BASE_URL}/` : `${SEO_BASE_URL}/${locale}/`
}

function upsertLink(selector: string, attrs: Record<string, string>): void {
  let el = document.head.querySelector<HTMLLinkElement>(selector)
  if (!el) {
    el = document.createElement('link')
    document.head.appendChild(el)
  }
  for (const [key, value] of Object.entries(attrs)) {
    el.setAttribute(key, value)
  }
}

function setOgUrl(url: string): void {
  let el = document.head.querySelector('meta[property="og:url"]')
  if (!el) {
    el = document.createElement('meta')
    el.setAttribute('property', 'og:url')
    document.head.appendChild(el)
  }
  el.setAttribute('content', url)
}

/**
 * Maintain per-language SEO tags on the landing page:
 *   - <link rel="canonical"> pointing at the current language URL
 *   - a full hreflang set: one <link rel="alternate"> per supported locale
 *     (self-referencing + siblings) plus hreflang="x-default" → `/`
 *   - og:url synced to the current language URL
 *
 * Elements are matched by attribute selectors and updated in place, so the
 * static defaults in index.html are corrected — never duplicated — after
 * hydration. Call only while a landing route (`/` or `/<locale>/`) is active;
 * on login/admin the tags are simply left untouched (those pages are
 * robots-disallowed and never crawled).
 */
export function updateLandingSeoLinks(locale: AppLocale): void {
  try {
    upsertLink('link[rel="canonical"]', { rel: 'canonical', href: localeUrl(locale) })
    for (const { code } of SUPPORTED_LOCALES) {
      upsertLink(`link[rel="alternate"][hreflang="${code}"]`, {
        rel: 'alternate',
        hreflang: code,
        href: localeUrl(code),
      })
    }
    upsertLink('link[rel="alternate"][hreflang="x-default"]', {
      rel: 'alternate',
      hreflang: 'x-default',
      href: localeUrl('en'),
    })
    setOgUrl(localeUrl(locale))
  } catch {
    // non-critical — static tags in index.html remain as the fallback
  }
}
