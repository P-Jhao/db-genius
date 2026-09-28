// SEO multi-language URL verification (temporary dev-server test).
// Neutralizes IP geolocation in every context so results are deterministic.
import { chromium } from 'playwright'

const BASE = 'http://localhost:5173'
const b = await chromium.launch()
let failures = 0

const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? `  (${detail})` : ''}`)
  if (!ok) failures++
}

const newPage = async (init) => {
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } })
  await ctx.route(/ipapi\.co|ip-api\.com/, (r) => r.abort()) // block geo providers
  await ctx.addInitScript(() => {
    try { sessionStorage.setItem('geo-locale', 'none') } catch {}
  })
  if (init) await ctx.addInitScript(init)
  const p = await ctx.newPage()
  return { ctx, p }
}

const seoSnapshot = (p) =>
  p.evaluate(() => ({
    htmlLang: document.documentElement.lang,
    canonical: document.querySelector('link[rel="canonical"]')?.getAttribute('href'),
    ogUrl: document.querySelector('meta[property="og:url"]')?.getAttribute('content'),
    alternates: [...document.querySelectorAll('link[rel="alternate"][hreflang]')].map((l) => [
      l.getAttribute('hreflang'),
      l.getAttribute('href'),
    ]),
  }))

const HREFLANGS = ['en', 'zh-CN', 'zh-TW', 'es', 'fr', 'ja', 'ms', 'x-default']

// ── 1. /zh-CN/ ──────────────────────────────────────────────────────────
{
  const { ctx, p } = await newPage()
  await p.goto(`${BASE}/zh-CN/`, { waitUntil: 'networkidle' })
  const s = await seoSnapshot(p)
  const h1 = (await p.textContent('h1').catch(() => '')) ?? ''
  check('zh-CN html lang', s.htmlLang === 'zh-CN', s.htmlLang)
  check('zh-CN h1 Chinese', /[一-龥]/.test(h1), h1.replace(/\s+/g, ' ').slice(0, 40))
  check('zh-CN canonical', s.canonical === 'https://db-genius.com/zh-CN/', s.canonical)
  check('zh-CN og:url', s.ogUrl === 'https://db-genius.com/zh-CN/', s.ogUrl)
  check(
    'zh-CN 8 alternates',
    HREFLANGS.every((h) => s.alternates.some(([k]) => k === h)) && s.alternates.length === 8,
    JSON.stringify(s.alternates.map(([k]) => k)),
  )
  check(
    'zh-CN alternate hrefs',
    s.alternates.every(([k, v]) =>
      k === 'en' || k === 'x-default' ? v === 'https://db-genius.com/' : v === `https://db-genius.com/${k}/`,
    ),
  )
  await ctx.close()
}

// ── 2. /es/ and /ja/ spot checks ────────────────────────────────────────
for (const [loc, h1re] of [
  ['es', /[áéíóúñ¿¡]|bases de datos/i],
  ['ja', /[぀-ヿ一-龥]/],
]) {
  const { ctx, p } = await newPage()
  await p.goto(`${BASE}/${loc}/`, { waitUntil: 'networkidle' })
  const s = await seoSnapshot(p)
  const h1 = (await p.textContent('h1').catch(() => '')) ?? ''
  check(`${loc} html lang`, s.htmlLang === loc, s.htmlLang)
  check(`${loc} h1 localized`, h1re.test(h1), h1.replace(/\s+/g, ' ').slice(0, 40))
  check(`${loc} canonical`, s.canonical === `https://db-genius.com/${loc}/`, s.canonical)
  check(`${loc} 8 alternates`, s.alternates.length === 8)
  await ctx.close()
}

// ── 3. / renders English (default en environment) ───────────────────────
{
  const { ctx, p } = await newPage()
  await p.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await p.waitForTimeout(800) // give any redirect a chance to fire
  check('root stays at /', new URL(p.url()).pathname === '/', p.url())
  const s = await seoSnapshot(p)
  const h1 = (await p.textContent('h1').catch(() => '')) ?? ''
  check('root html lang en', s.htmlLang === 'en', s.htmlLang)
  check('root h1 English', !/[一-龥぀-ヿ]/.test(h1), h1.replace(/\s+/g, ' ').slice(0, 40))
  check('root canonical', s.canonical === 'https://db-genius.com/', s.canonical)
  await ctx.close()
}

// ── 4. /en/ redirects to / ──────────────────────────────────────────────
{
  const { ctx, p } = await newPage()
  await p.goto(`${BASE}/en/`, { waitUntil: 'networkidle' })
  await p.waitForTimeout(500)
  check('/en/ -> /', new URL(p.url()).pathname === '/', p.url())
  await ctx.close()
}

// ── 5. switcher on /es/ -> 日本語 -> /ja/ ────────────────────────────────
{
  const { ctx, p } = await newPage()
  await p.goto(`${BASE}/es/`, { waitUntil: 'networkidle' })
  await p.locator('.lang-switcher').first().click()
  await p.waitForTimeout(400)
  await p.locator('li, .arco-dropdown-option').filter({ hasText: '日本語' }).first().click()
  await p.waitForTimeout(800)
  const url = new URL(p.url()).pathname
  const s = await seoSnapshot(p)
  const h1 = (await p.textContent('h1').catch(() => '')) ?? ''
  check('switch es->ja URL', url === '/ja/', url)
  check('switch es->ja html lang', s.htmlLang === 'ja', s.htmlLang)
  check('switch es->ja h1 Japanese', /[぀-ヿ一-龥]/.test(h1), h1.replace(/\s+/g, ' ').slice(0, 40))
  check('switch es->ja canonical', s.canonical === 'https://db-genius.com/ja/', s.canonical)
  await ctx.close()
}

// ── 6. localStorage app-locale=fr + first visit / -> /fr/ ───────────────
{
  const { ctx, p } = await newPage(() => localStorage.setItem('app-locale', 'fr'))
  await p.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await p.waitForTimeout(500)
  const url = new URL(p.url()).pathname
  const s = await seoSnapshot(p)
  check('stored fr redirects / -> /fr/', url === '/fr/', url)
  check('stored fr html lang', s.htmlLang === 'fr', s.htmlLang)
  check('stored fr canonical', s.canonical === 'https://db-genius.com/fr/', s.canonical)
  await ctx.close()
}

// ── 6b. legacy ?lang=ms redirect ─────────────────────────────────────────
{
  const { ctx, p } = await newPage()
  await p.goto(`${BASE}/?lang=ms`, { waitUntil: 'networkidle' })
  await p.waitForTimeout(500)
  const url = new URL(p.url())
  check('?lang=ms -> /ms/', url.pathname === '/ms/' && !url.search.includes('lang'), p.url())
  await ctx.close()
}

// ── 7. sitemap.xml reachable with 7 urls ─────────────────────────────────
{
  const res = await b.newContext().then((c) => c.request.get(`${BASE}/sitemap.xml`))
  const body = await res.text()
  const urlCount = (body.match(/<url>/g) || []).length
  check('sitemap 200', res.status() === 200, String(res.status()))
  check('sitemap has 7 <url>', urlCount === 7, `count=${urlCount}`)
  check('sitemap has xhtml namespace', body.includes('xmlns:xhtml="http://www.w3.org/1999/xhtml"'))
  check('sitemap no /contact-sales', !body.includes('contact-sales'))
  check(
    'sitemap lists all locales',
    ['zh-CN', 'zh-TW', 'es', 'fr', 'ja', 'ms'].every((l) => body.includes(`<loc>https://db-genius.com/${l}/</loc>`)),
  )
}

await b.close()
console.log(failures === 0 ? '\nALL CHECKS PASSED' : `\n${failures} CHECK(S) FAILED`)
process.exit(failures === 0 ? 0 : 1)
