import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { DbConfigVO } from '../types'
import { getDbConfigs } from '../api/dbConfig'

export const useDbConfigStore = defineStore('dbConfig', () => {
  const configs = ref<DbConfigVO[]>([])
  const loading = ref(false)

  async function load() {
    loading.value = true
    try {
      const res = await getDbConfigs()
      configs.value = res.data
    } finally {
      loading.value = false
    }
  }

  const connectedConfigs = computed(() => configs.value.filter((c) => c.status === 1))

  return { configs, loading, load, connectedConfigs }
})
