<script setup lang="ts">
import GitHubIcon from './GitHubIcon.vue'
import { GITHUB_REPO_URL } from '../../config/site'
</script>

<template>
  <div class="trial-banner">
    <span class="trial-banner__text">
      {{ $t('comps.trial.text') }}
    </span>
    <a-button
      v-if="GITHUB_REPO_URL"
      type="text"
      size="mini"
      class="trial-banner__link"
      :href="GITHUB_REPO_URL"
      target="_blank"
    >
      <template #icon><GitHubIcon :size="14" /></template>
      GitHub
    </a-button>
  </div>
</template>

<style scoped lang="scss">
.trial-banner {
  min-height: 48px;
  padding: 8px 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  flex-wrap: wrap;
  background: #fff7e6;
  color: #d46b08;
  border-bottom: 1px solid #ffd591;
  text-align: center;
  font-size: 14px;
}

.trial-banner__text {
  line-height: 1.5;
}

.trial-banner__link {
  color: rgb(var(--primary-6));
  padding: 0;
  height: auto;
  font-size: 14px;

  &:hover {
    color: rgb(var(--primary-7));
  }
}
</style>
