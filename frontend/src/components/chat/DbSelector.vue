<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import type { DbConfigVO } from '../../types'
import { getDbConfigs } from '../../api/dbConfig'

const props = withDefaults(
  defineProps<{
    modelValue?: number[]
    preId?: number | null
    testId?: number | null
    variant?: 'multi' | 'compare'
  }>(),
  {
    modelValue: () => [],
    preId: null,
    testId: null,
    variant: 'multi',
  }
)

const emit = defineEmits<{
  'update:modelValue': [value: number[]]
  'update:preId': [value: number | null]
  'update:testId': [value: number | null]
}>()

const configs = ref<DbConfigVO[]>([])
const loading = ref(false)

const connectedConfigs = computed(() => configs.value.filter((c) => c.status === 1))
const options = computed(() =>
  connectedConfigs.value.map((c) => ({
    value: c.id,
    label: c.name,
    detail: `${c.dbName}@${c.host}:${c.port}`,
  }))
)

function formatLabel(data: { value?: unknown; label?: string }) {
  const opt = options.value.find((o) => o.value === data.value)
  return opt ? opt.label : data.label ?? ''
}

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
  <div class="db-selector" :class="[`db-selector--${variant}`]">
    <a-spin :loading="loading" :size="16">
      <template v-if="variant === 'compare'">
        <div class="compare-row">
          <a-select
            :model-value="preId ?? undefined"
            :placeholder="$t('chat.selector.preShort')"
            allow-clear
            :format-label="formatLabel"
            :trigger-props="{ position: 'top' }"
            @update:model-value="emit('update:preId', ($event as number | null) ?? null)"
          >
            <a-option v-for="opt in options" :key="opt.value" :value="opt.value">
              <span class="option-name">{{ opt.label }}</span>
              <span class="option-detail">{{ opt.detail }}</span>
            </a-option>
          </a-select>
          <icon-right class="arrow-icon" />
          <a-select
            :model-value="testId ?? undefined"
            :placeholder="$t('chat.selector.testShort')"
            allow-clear
            :format-label="formatLabel"
            :trigger-props="{ position: 'top' }"
            @update:model-value="emit('update:testId', ($event as number | null) ?? null)"
          >
            <a-option v-for="opt in options" :key="opt.value" :value="opt.value">
              <span class="option-name">{{ opt.label }}</span>
              <span class="option-detail">{{ opt.detail }}</span>
            </a-option>
          </a-select>
        </div>
      </template>
      <template v-else>
        <a-select
          :model-value="modelValue"
          :placeholder="$t('chat.selector.selectDb')"
          multiple
          allow-clear
          :max-tag-count="2"
          :format-label="formatLabel"
          :trigger-props="{ position: 'top' }"
          @update:model-value="emit('update:modelValue', ($event as number[]) || [])"
        >
          <a-option v-for="opt in options" :key="opt.value" :value="opt.value">
            <span class="option-name">{{ opt.label }}</span>
            <span class="option-detail">{{ opt.detail }}</span>
          </a-option>
        </a-select>
      </template>
      <div v-if="connectedConfigs.length === 0 && !loading" class="db-empty">
        <span>{{ $t('chat.selector.empty') }}<router-link to="/admin/db-config">{{ $t('chat.selector.emptyLink') }}</router-link></span>
      </div>
    </a-spin>
  </div>
</template>

<style scoped lang="scss">
.db-selector {
  min-width: 160px;

  :deep(.arco-select) {
    width: 100%;
  }

  :deep(.arco-select-view-value) {
    overflow: hidden;
  }

  :deep(.arco-tag) {
    max-width: 100%;

    .arco-tag-content {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }
}

.compare-row {
  display: flex;
  align-items: center;
  gap: 6px;

  :deep(.arco-select) {
    flex: 1;
    min-width: 0;
  }

  .arrow-icon {
    color: var(--color-text-4);
    flex-shrink: 0;
  }
}

.option-name {
  font-weight: 500;
}

.option-detail {
  margin-left: 8px;
  font-size: 12px;
  color: var(--color-text-3);
}

.db-empty {
  margin-top: 4px;
  font-size: 12px;
  color: var(--color-text-3);

  a {
    color: rgb(var(--primary-6));
  }
}

@media (max-width: 768px) {
  .db-selector {
    min-width: 0;
  }

  .compare-row {
    flex-direction: column;
    align-items: stretch;
    gap: 4px;

    :deep(.arco-select) {
      width: 100%;
    }

    .arrow-icon {
      transform: rotate(90deg);
      align-self: center;
    }
  }
}
</style>
