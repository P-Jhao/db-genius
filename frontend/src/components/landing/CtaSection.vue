<script setup lang="ts">
import GitHubIcon from '../common/GitHubIcon.vue'
import { GITHUB_REPO_URL } from '../../config/site'

defineEmits<{
  cta: []
}>()
</script>

<template>
  <section class="cta" :aria-label="$t('landing.cta.ariaLabel')">
    <div class="cta-inner">
      <h2>{{ $t('landing.cta.title') }}</h2>
      <p>{{ $t('landing.cta.subtitle') }}</p>
      <div class="cta-actions">
        <a-button type="primary" size="large" class="cta-primary" @click="$emit('cta')">
          {{ $t('landing.cta.button') }}
          <template #icon><icon-right /></template>
        </a-button>
        <a-button
          v-if="GITHUB_REPO_URL"
          size="large"
          class="cta-ghost"
          :href="GITHUB_REPO_URL"
          target="_blank"
        >
          <template #icon><GitHubIcon :size="18" /></template>
          GitHub
        </a-button>
      </div>
    </div>
  </section>
</template>

<style scoped lang="scss">
.cta {
  padding: 96px 24px;
  background:
    radial-gradient(ellipse 50% 60% at 80% 20%, rgba(20, 201, 201, 0.35), transparent),
    linear-gradient(135deg, #0d2054 0%, #165dff 100%);
}

.cta-inner {
  max-width: 720px;
  margin: 0 auto;
  text-align: center;

  h2 {
    font-size: 36px;
    font-weight: 800;
    color: #fff;
    margin-bottom: 12px;
  }

  p {
    font-size: 16px;
    color: rgba(255, 255, 255, 0.75);
    margin-bottom: 36px;
  }
}

.cta-actions {
  display: flex;
  justify-content: center;
  gap: 16px;
}

.cta-primary {
  background: #fff !important;
  color: #165dff !important;
  border: none !important;
  font-weight: 600;
}

.cta-ghost {
  background: transparent !important;
  color: #fff !important;
  border: 1px solid rgba(255, 255, 255, 0.5) !important;

  &:hover {
    border-color: #fff !important;
    background: rgba(255, 255, 255, 0.08) !important;
  }
}

@media (max-width: 768px) {
  .cta {
    padding: 64px 20px;
  }

  .cta-inner h2 {
    font-size: 24px;
  }

  .cta-actions {
    flex-direction: column;
    align-items: stretch;

    .arco-btn {
      width: 100%;
    }
  }
}
</style>
