<script setup lang="ts">
import { onMounted, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useTrialStore } from './stores/trial'
import TrialBanner from './components/common/TrialBanner.vue'
import ComplianceNotice from './components/common/ComplianceNotice.vue'
import { i18n, currentArcoLocale, updateDocumentMeta, getCurrentLocale } from './i18n'
import { updateLandingSeoLinks } from './i18n/seo'

const trialStore = useTrialStore()
const route = useRoute()

const showBanner = computed(() => trialStore.isTrial)

// 合规提示条：仅出现在主页（落地页），且不区分开源版 / 正式版。
const isLanding = computed(
  () => route.name === 'landing' || route.name === 'landing-locale',
)

onMounted(() => {
  trialStore.loadTrialStatus()
})

// Keep document.title / meta description in sync with the active locale, and
// maintain canonical + hreflang alternate links while on a landing route.
watch(
  [() => i18n.global.locale.value, () => route.name],
  () => {
    updateDocumentMeta()
    if (route.name === 'landing' || route.name === 'landing-locale') {
      updateLandingSeoLinks(getCurrentLocale())
    }
  },
  { immediate: true },
)
</script>

<template>
  <a-config-provider :locale="currentArcoLocale">
    <div class="app-root" :style="showBanner ? { '--banner-height': '48px' } : undefined">
      <ComplianceNotice v-if="isLanding" />
      <TrialBanner v-if="showBanner" />
      <router-view />
    </div>
  </a-config-provider>
</template>

<style lang="scss">
.app-root {
  --banner-height: 0px;
}
</style>
