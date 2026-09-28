<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const faqs = computed(() => [
  { q: t('landing.faq.items.free.q'), a: t('landing.faq.items.free.a') },
  { q: t('landing.faq.items.databases.q'), a: t('landing.faq.items.databases.a') },
  { q: t('landing.faq.items.client.q'), a: t('landing.faq.items.client.a') },
  { q: t('landing.faq.items.safety.q'), a: t('landing.faq.items.safety.a') },
  { q: t('landing.faq.items.security.q'), a: t('landing.faq.items.security.a') },
  { q: t('landing.faq.items.contribute.q'), a: t('landing.faq.items.contribute.a') },
])
</script>

<template>
  <section id="faq" class="faq" :aria-label="$t('landing.faq.ariaLabel')">
    <div class="faq-inner">
      <div class="section-header">
        <h2>{{ $t('landing.faq.title') }}</h2>
        <p>{{ $t('landing.faq.subtitle') }}</p>
      </div>
      <a-collapse :default-active-key="[0]" class="faq-collapse" accordion>
        <a-collapse-item v-for="(f, i) in faqs" :key="i" :header="f.q">
          <p class="faq-answer">{{ f.a }}</p>
        </a-collapse-item>
      </a-collapse>
    </div>
  </section>
</template>

<style scoped lang="scss">
.faq {
  padding: 80px 24px;
  background: #fff;
}

.faq-inner {
  max-width: 860px;
  margin: 0 auto;
}

.section-header {
  text-align: center;
  margin-bottom: 40px;

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

.faq-collapse {
  :deep(.arco-collapse-item-header) {
    font-size: 15px;
    font-weight: 600;
    color: var(--color-text-1);
    padding-top: 18px;
    padding-bottom: 18px;
  }
}

.faq-answer {
  font-size: 14px;
  line-height: 1.9;
  color: var(--color-text-3);
  margin: 0;
}

@media (max-width: 768px) {
  .faq {
    padding: 56px 20px;
  }
}
</style>
