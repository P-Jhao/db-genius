<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import type { DbConfigVO } from '../../types'
import { getDbConfigs } from '../../api/dbConfig'

const props = defineProps<{
  preId: number | null
  testId: number | null
}>()

const emit = defineEmits<{
  'update:preId': [value: number | null]
  'update:testId': [value: number | null]
}>()

const configs = ref<DbConfigVO[]>([])
const loading = ref(false)

const connectedConfigs = computed(() => configs.value.filter((c) => c.status === 1))

onMounted(async () => {
  loading.value = true
  try {
    const res = await getDbConfigs()
    configs.value = res.data
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="compare-selector">
    <a-spin :loading="loading" :size="16">
      <div class="selector-row">
        <div class="selector-group">
          <span class="selector-label">{{ $t('chat.selector.preLabel') }}</span>
          <a-select
            :model-value="props.preId ?? undefined"
            :placeholder="$t('chat.selector.prePlaceholder')"
            @update:model-value="emit('update:preId', ($event as number | null) ?? null)"
            allow-clear
          >
            <a-option
              v-for="config in connectedConfigs"
              :key="config.id"
              :value="config.id"
              :label="config.name"
            />
          </a-select>
        </div>
        <icon-right class="arrow-icon" />
        <div class="selector-group">
          <span class="selector-label">{{ $t('chat.selector.testLabel') }}</span>
          <a-select
            :model-value="props.testId ?? undefined"
            :placeholder="$t('chat.selector.testPlaceholder')"
            @update:model-value="emit('update:testId', ($event as number | null) ?? null)"
            allow-clear
          >
            <a-option
              v-for="config in connectedConfigs"
              :key="config.id"
              :value="config.id"
              :label="config.name"
            />
          </a-select>
        </div>
      </div>
    </a-spin>
  </div>
</template>

<style scoped lang="scss">
.compare-selector {
  padding: 4px 0;
}

.selector-row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}

.selector-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  min-width: 0;

  .selector-label {
    font-size: 12px;
    color: var(--color-text-3);
  }
}

.arrow-icon {
  color: var(--color-text-4);
  flex-shrink: 0;
  margin-bottom: 8px;
}

@media (max-width: 768px) {
  .selector-row {
    flex-direction: column;
    align-items: stretch;
  }

  .arrow-icon {
    transform: rotate(90deg);
    align-self: center;
    margin: 0;
  }
}
</style>
