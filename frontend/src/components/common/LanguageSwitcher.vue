<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { IconLanguage } from '@arco-design/web-vue/es/icon'
import { SUPPORTED_LOCALES, applyUserChoice } from '../../i18n'
import type { AppLocale } from '../../i18n'

withDefaults(
  defineProps<{
    /** dark = for dark navigation bars (landing page top nav); light = admin header */
    dark?: boolean
  }>(),
  { dark: false },
)

const { locale, t } = useI18n()
const route = useRoute()
const router = useRouter()

/** Landing pages (`/` and `/<locale>/`) keep one URL per language. */
const isLanding = computed(() => route.name === 'landing' || route.name === 'landing-locale')

const currentName = computed(
  () => SUPPORTED_LOCALES.find((l) => l.code === locale.value)?.nativeName ?? locale.value,
)

function isActive(code: AppLocale) {
  return locale.value === code
}

function onSelect(value: string | number | Record<string, unknown> | undefined) {
  const target = SUPPORTED_LOCALES.find((l) => l.code === value)
  if (!target) return
  applyUserChoice(target.code)
  if (isLanding.value) {
    const path = target.code === 'en' ? '/' : `/${target.code}/`
    if (route.path !== path) router.replace(path)
  }
}
</script>

<template>
  <a-dropdown trigger="click" position="br" @select="onSelect">
    <button
      type="button"
      class="lang-switcher"
      :class="{ 'lang-switcher--dark': dark }"
      :aria-label="t('common.switchLanguage')"
      :title="t('common.switchLanguage')"
    >
      <IconLanguage class="lang-switcher-icon" />
      <span class="lang-switcher-name">{{ currentName }}</span>
    </button>
    <template #content>
      <a-doption
        v-for="item in SUPPORTED_LOCALES"
        :key="item.code"
        :value="item.code"
        :class="{ 'lang-option--active': isActive(item.code) }"
      >
        <span class="lang-option-label">{{ item.nativeName }}</span>
        <icon-check v-if="isActive(item.code)" class="lang-option-check" />
      </a-doption>
    </template>
  </a-dropdown>
</template>

<style scoped lang="scss">
.lang-switcher {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--color-text-2);
  font-size: 14px;
  cursor: pointer;
  transition: background-color 0.15s ease, color 0.15s ease, border-color 0.15s ease;

  &:hover {
    background: var(--color-fill-2);
    color: var(--color-text-1);
  }
}

.lang-switcher--dark {
  color: rgba(255, 255, 255, 0.85);

  &:hover {
    background: rgba(255, 255, 255, 0.12);
    color: #fff;
  }
}

.lang-switcher-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.lang-switcher-name {
  white-space: nowrap;
}

.lang-option-label {
  margin-right: 12px;
}

.lang-option--active .lang-option-label {
  color: rgb(var(--primary-6));
  font-weight: 500;
}

.lang-option-check {
  color: rgb(var(--primary-6));
}

/* Narrow screens: icon only */
@media (max-width: 640px) {
  .lang-switcher {
    padding: 0 8px;
  }

  .lang-switcher-name {
    display: none;
  }
}
</style>
