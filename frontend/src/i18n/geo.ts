import type { AppLocale } from './index'

const GEO_CACHE_KEY = 'geo-locale'
const GEO_TIMEOUT_MS = 3500

/**
 * ISO-3166 alpha-2 country code -> app locale.
 * Everything not listed falls back to English.
 */
const COUNTRY_TO_LOCALE: Record<string, AppLocale> = {
  CN: 'zh-CN',
  TW: 'zh-TW',
  HK: 'zh-TW',
  MO: 'zh-TW',
  JP: 'ja',
  FR: 'fr',
  ES: 'es',
  MX: 'es',
  AR: 'es',
  BO: 'es',
  CL: 'es',
  CO: 'es',
  CR: 'es',
  CU: 'es',
  DO: 'es',
  EC: 'es',
  SV: 'es',
  GQ: 'es',
  GT: 'es',
  HN: 'es',
  NI: 'es',
  PA: 'es',
  PY: 'es',
  PE: 'es',
  PR: 'es',
  UY: 'es',
  VE: 'es',
  MY: 'ms',
}

function countryToLocale(countryCode: unknown): AppLocale | null {
  if (typeof countryCode !== 'string' || !countryCode) return null
  return COUNTRY_TO_LOCALE[countryCode.toUpperCase()] ?? null
}

function readCache(): AppLocale | null | undefined {
  try {
    const cached = sessionStorage.getItem(GEO_CACHE_KEY)
    // 'null' string marks "geo detection ran but resolved to nothing" so we
    // do not hit the network again within the same session.
    if (cached === 'none') return null
    if (cached) return cached as AppLocale
    return undefined
  } catch {
    return undefined
  }
}

function writeCache(locale: AppLocale | null): void {
  try {
    sessionStorage.setItem(GEO_CACHE_KEY, locale ?? 'none')
  } catch {
    // storage unavailable (private mode etc.) — ignore silently
  }
}

async function fetchCountryCode(): Promise<string | null> {
  try {
    const res = await fetch('https://ipapi.co/json/', {
      signal: AbortSignal.timeout(GEO_TIMEOUT_MS),
    })
    if (res.ok) {
      const data = (await res.json()) as { country_code?: string }
      if (data.country_code) return data.country_code
    }
  } catch {
    // fall through to the backup provider
  }
  try {
    const res = await fetch('https://ip-api.com/json/?fields=countryCode', {
      signal: AbortSignal.timeout(GEO_TIMEOUT_MS),
    })
    if (res.ok) {
      const data = (await res.json()) as { countryCode?: string }
      if (data.countryCode) return data.countryCode
    }
  } catch {
    // both providers failed — caller falls back to navigator language
  }
  return null
}

/**
 * Resolve a locale from IP geolocation.
 *
 * - Result is cached in sessionStorage (`geo-locale`); one network round-trip
 *   per session at most.
 * - Never throws: every network/storage failure resolves to `null` and the
 *   caller keeps the current (navigator/fallback) locale.
 * - Returns `null` when the country has no non-English mapping (English is
 *   already the fallback locale, so no switch is needed).
 */
export async function detectGeoLocale(): Promise<AppLocale | null> {
  const cached = readCache()
  if (cached !== undefined) return cached

  const countryCode = await fetchCountryCode()
  // Unknown/unmapped countries resolve to English, which is the fallback
  // anyway, so there is nothing to switch to.
  const locale = countryToLocale(countryCode)
  writeCache(locale)
  return locale
}
