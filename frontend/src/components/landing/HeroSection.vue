<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import GitHubIcon from '../common/GitHubIcon.vue'
import { GITHUB_REPO_URL } from '../../config/site'

defineEmits<{
  cta: []
}>()

const { locale } = useI18n()

/** 按当前语言解析截图路径；加载失败时回退到根目录英文默认图 */
const heroImg = computed(() => `/landing/${locale.value}/db-genius-ai-sql-query.jpg`)

function fallbackImg(e: Event) {
  const img = e.target as HTMLImageElement
  const fallback = '/landing/db-genius-ai-sql-query.jpg'
  if (!img.src.endsWith(fallback)) img.src = fallback
}
</script>

<template>
  <section class="hero" :aria-label="$t('landing.hero.ariaLabel')">
    <div class="hero-inner">
      <div class="hero-content">
        <a-tag color="arcoblue" size="medium">{{ $t('landing.hero.tag') }}</a-tag>
        <h1>{{ $t('landing.hero.titleLine1') }}<br /><span class="gradient-text">{{ $t('landing.hero.titleLine2') }}</span></h1>
        <p class="hero-desc">
          {{ $t('landing.hero.desc') }}
        </p>
        <div class="hero-actions">
          <a-button type="primary" size="large" @click="$emit('cta')">
            {{ $t('landing.hero.cta') }}
            <template #icon><icon-right /></template>
          </a-button>
          <a-button v-if="GITHUB_REPO_URL" size="large" :href="GITHUB_REPO_URL" target="_blank">
            <template #icon><GitHubIcon :size="18" /></template>
            GitHub
          </a-button>
        </div>
        <ul class="hero-trust">
          <li><icon-check-circle-fill /> {{ $t('landing.hero.trust1') }}</li>
          <li><icon-check-circle-fill /> {{ $t('landing.hero.trust2') }}</li>
          <li><icon-check-circle-fill /> {{ $t('landing.hero.trust3') }}</li>
        </ul>
      </div>
      <div class="hero-visual">
        <figure class="browser-frame">
          <div class="browser-bar" aria-hidden="true">
            <span class="dot red" /><span class="dot yellow" /><span class="dot green" />
            <span class="browser-url">db-genius.pjhao.xyz/admin/chat</span>
          </div>
          <img
            :src="heroImg"
            :alt="$t('landing.hero.screenshotAlt')"
            width="1600"
            height="1000"
            fetchpriority="high"
            @error="fallbackImg"
          />
        </figure>
        <div class="float-card float-card-1" aria-hidden="true">
          <icon-thunderbolt /> {{ $t('landing.hero.float1') }}
        </div>
        <div class="float-card float-card-2" aria-hidden="true">
          <icon-safe /> {{ $t('landing.hero.float2') }}
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped lang="scss">
.hero {
  padding: 72px 24px 80px;
  background:
    radial-gradient(ellipse 60% 50% at 85% 10%, rgba(20, 201, 201, 0.1), transparent),
    radial-gradient(ellipse 50% 40% at 10% 20%, rgba(22, 93, 255, 0.08), transparent),
    linear-gradient(180deg, #fff 0%, #f7f8fa 100%);
  overflow: hidden;
}

.hero-inner {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: 56px;
}

.hero-content {
  flex: 0 0 42%;
  min-width: 0;

  h1 {
    font-size: 46px;
    font-weight: 800;
    line-height: 1.25;
    margin: 20px 0 16px;
    color: var(--color-text-1);
  }

  .gradient-text {
    background: linear-gradient(90deg, #165dff, #14c9c9);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
  }

  .hero-desc {
    font-size: 16px;
    line-height: 1.8;
    color: var(--color-text-3);
    margin-bottom: 32px;
  }
}

.hero-actions {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
}

.hero-trust {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;

  li {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 14px;
    color: var(--color-text-2);

    .arco-icon {
      color: #00b42a;
    }
  }
}

.hero-visual {
  flex: 1;
  min-width: 0;
  position: relative;
}

.browser-frame {
  margin: 0;
  border-radius: 14px;
  background: #fff;
  border: 1px solid var(--color-border-1);
  box-shadow: 0 24px 64px rgba(22, 93, 255, 0.14);
  overflow: hidden;

  .browser-bar {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 10px 14px;
    background: #f2f3f5;
    border-bottom: 1px solid var(--color-border-1);

    .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      &.red { background: #ff5f57; }
      &.yellow { background: #febc2e; }
      &.green { background: #28c840; }
    }

    .browser-url {
      margin-left: 10px;
      font-size: 12px;
      color: var(--color-text-4);
      background: #fff;
      border-radius: 6px;
      padding: 3px 12px;
      flex: 1;
      max-width: 320px;
    }
  }

  img {
    display: block;
    width: 100%;
    height: auto;
  }
}

.float-card {
  position: absolute;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.1);
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-1);
  white-space: nowrap;

  .arco-icon {
    font-size: 16px;
  }
}

.float-card-1 {
  top: 18%;
  left: -24px;

  .arco-icon { color: #165dff; }
}

.float-card-2 {
  bottom: 12%;
  right: -16px;

  .arco-icon { color: #00b42a; }
}

@media (max-width: 900px) {
  .hero {
    padding: 48px 20px 56px;
  }

  .hero-inner {
    flex-direction: column;
    gap: 48px;
  }

  .hero-content {
    flex: none;
    text-align: center;

    h1 { font-size: 30px; }
    .hero-desc { margin-left: auto; margin-right: auto; }
  }

  .hero-actions {
    justify-content: center;
    flex-wrap: wrap;
  }
  .hero-trust { align-items: center; }
  .float-card { display: none; }
}
</style>
