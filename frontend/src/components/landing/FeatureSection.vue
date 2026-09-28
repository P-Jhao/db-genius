<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const features = computed(() => [
  {
    icon: 'sql',
    title: t('landing.features.items.sql.title'),
    desc: t('landing.features.items.sql.desc'),
  },
  {
    icon: 'workflow',
    title: t('landing.features.items.workflow.title'),
    desc: t('landing.features.items.workflow.desc'),
  },
  {
    icon: 'compare',
    title: t('landing.features.items.compare.title'),
    desc: t('landing.features.items.compare.desc'),
  },
])
</script>

<template>
  <section id="features" class="features">
    <div class="features-inner">
      <div class="section-header">
        <h2>{{ $t('landing.features.title') }}</h2>
        <p>{{ $t('landing.features.subtitle') }}</p>
      </div>
      <div class="feature-grid">
        <div v-for="f in features" :key="f.icon" class="feature-card">
          <div class="feature-icon">
            <svg v-if="f.icon === 'sql'" viewBox="0 0 48 48" fill="none" width="48" height="48">
              <rect width="48" height="48" rx="12" fill="#165DFF" opacity="0.1"/>
              <path d="M14 18l6 6-6 6M24 30h10" stroke="#165DFF" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <svg v-else-if="f.icon === 'workflow'" viewBox="0 0 48 48" fill="none" width="48" height="48">
              <rect width="48" height="48" rx="12" fill="#0FC6C2" opacity="0.1"/>
              <rect x="10" y="10" width="12" height="12" rx="3" stroke="#0FC6C2" stroke-width="2"/>
              <rect x="26" y="10" width="12" height="12" rx="3" stroke="#0FC6C2" stroke-width="2"/>
              <rect x="18" y="26" width="12" height="12" rx="3" stroke="#0FC6C2" stroke-width="2"/>
              <path d="M16 22v4h16v-4" stroke="#0FC6C2" stroke-width="2" stroke-linecap="round"/>
            </svg>
            <svg v-else viewBox="0 0 48 48" fill="none" width="48" height="48">
              <rect width="48" height="48" rx="12" fill="#F7BA1E" opacity="0.1"/>
              <circle cx="18" cy="18" r="6" stroke="#F7BA1E" stroke-width="2"/>
              <circle cx="30" cy="30" r="6" stroke="#F7BA1E" stroke-width="2"/>
              <path d="M22 22l4 4" stroke="#F7BA1E" stroke-width="2" stroke-linecap="round"/>
              <path d="M12 36l4-4M32 12l4-4" stroke="#F7BA1E" stroke-width="2" stroke-linecap="round"/>
            </svg>
          </div>
          <h3>{{ f.title }}</h3>
          <p>{{ f.desc }}</p>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped lang="scss">
.features {
  padding: 80px 24px;
  background: #fff;
}

.features-inner {
  max-width: 1200px;
  margin: 0 auto;
}

.section-header {
  text-align: center;
  margin-bottom: 48px;

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

.feature-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
}

.feature-card {
  padding: 32px 24px;
  border-radius: 12px;
  border: 1px solid var(--color-border-1);
  transition: all 0.3s;

  &:hover {
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
    transform: translateY(-2px);
  }

  .feature-icon {
    margin-bottom: 20px;
  }

  h3 {
    font-size: 18px;
    font-weight: 600;
    margin-bottom: 8px;
    color: var(--color-text-1);
  }

  p {
    font-size: 14px;
    line-height: 1.6;
    color: var(--color-text-3);
  }
}

@media (max-width: 768px) {
  .features {
    padding: 56px 20px;
  }

  .feature-grid {
    grid-template-columns: 1fr;
  }
}
</style>
