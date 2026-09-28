<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { t, locale } = useI18n()

const activeTab = ref('sql')

/** 按当前语言解析截图路径；加载失败时回退到根目录英文默认图 */
function localizedImg(name: string): string {
  return `/landing/${locale.value}/${name}.jpg`
}

function fallbackImg(e: Event, name: string) {
  const img = e.target as HTMLImageElement
  const fallback = `/landing/${name}.jpg`
  if (!img.src.endsWith(fallback)) img.src = fallback
}

const showcases = computed(() => [
  {
    key: 'sql',
    tab: t('landing.showcase.items.sql.tab'),
    title: t('landing.showcase.items.sql.title'),
    desc: t('landing.showcase.items.sql.desc'),
    img: localizedImg('db-genius-ai-sql-query'),
    name: 'db-genius-ai-sql-query',
    alt: t('landing.showcase.items.sql.alt'),
  },
  {
    key: 'intent',
    tab: t('landing.showcase.items.intent.tab'),
    title: t('landing.showcase.items.intent.title'),
    desc: t('landing.showcase.items.intent.desc'),
    img: localizedImg('db-genius-ai-intent-recognition'),
    name: 'db-genius-ai-intent-recognition',
    alt: t('landing.showcase.items.intent.alt'),
  },
  {
    key: 'compare',
    tab: t('landing.showcase.items.compare.tab'),
    title: t('landing.showcase.items.compare.title'),
    desc: t('landing.showcase.items.compare.desc'),
    img: localizedImg('db-genius-database-compare'),
    name: 'db-genius-database-compare',
    alt: t('landing.showcase.items.compare.alt'),
  },
  {
    key: 'config',
    tab: t('landing.showcase.items.config.tab'),
    title: t('landing.showcase.items.config.title'),
    desc: t('landing.showcase.items.config.desc'),
    img: localizedImg('db-genius-database-config'),
    name: 'db-genius-database-config',
    alt: t('landing.showcase.items.config.alt'),
  },
])

const current = computed(() => showcases.value.find((s) => s.key === activeTab.value) ?? showcases.value[0])
</script>

<template>
  <section id="showcase" class="showcase" :aria-label="$t('landing.showcase.ariaLabel')">
    <div class="showcase-inner">
      <div class="section-header">
        <h2>{{ $t('landing.showcase.title') }}</h2>
        <p>{{ $t('landing.showcase.subtitle') }}</p>
      </div>
      <a-tabs v-model:active-key="activeTab" type="capsule" position="top" class="showcase-tabs">
        <a-tab-pane v-for="s in showcases" :key="s.key" :title="s.tab" />
      </a-tabs>
      <div class="showcase-body">
        <!-- 只渲染当前激活的面板：v-show 隐藏的懒加载图片不会发请求，
             切 Tab 后也不触发加载，会导致图片裂图，因此这里直接按 key 重渲染 -->
        <div class="showcase-panel">
          <div class="showcase-text">
            <h3>{{ current.title }}</h3>
            <p>{{ current.desc }}</p>
          </div>
          <figure class="showcase-figure">
            <img
              :key="current.key"
              :src="current.img"
              :alt="current.alt"
              width="1600"
              height="1000"
              @error="fallbackImg($event, current.name)"
            />
          </figure>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped lang="scss">
.showcase {
  padding: 80px 24px;
  background: #f7f8fa;
}

.showcase-inner {
  max-width: 1200px;
  margin: 0 auto;
}

.section-header {
  text-align: center;
  margin-bottom: 32px;

  h2 {
    font-size: 32px;
    font-weight: 700;
    color: var(--color-text-1);
    margin-bottom: 8px;
  }

  p {
    font-size: 16px;
    color: var(--color-text-3);
  }
}

.showcase-tabs {
  margin-bottom: 32px;

  :deep(.arco-tabs-nav-tab) {
    justify-content: center;
  }
}

.showcase-panel {
  display: flex;
  align-items: center;
  gap: 48px;
}

.showcase-text {
  flex: 0 0 34%;

  h3 {
    font-size: 26px;
    font-weight: 700;
    color: var(--color-text-1);
    margin-bottom: 16px;
    line-height: 1.4;
  }

  p {
    font-size: 15px;
    line-height: 1.9;
    color: var(--color-text-3);
  }
}

.showcase-figure {
  flex: 1;
  margin: 0;
  min-width: 0;
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid var(--color-border-1);
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.08);

  img {
    display: block;
    width: 100%;
    height: auto;
  }
}

@media (max-width: 900px) {
  .showcase {
    padding: 56px 20px;
  }

  .showcase-panel {
    flex-direction: column;
    gap: 24px;
  }

  .showcase-text {
    flex: none;
    text-align: center;

    h3 { font-size: 22px; }
  }

  /* 窄屏下 Tab 可横向滑动，避免溢出导致整页错位 */
  .showcase-tabs {
    :deep(.arco-tabs-nav) {
      max-width: 100%;
      overflow-x: auto;
      scrollbar-width: none;

      &::-webkit-scrollbar {
        display: none;
      }
    }

    :deep(.arco-tabs-nav-tab) {
      justify-content: flex-start;
    }
  }
}
</style>
