import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getTrialStatus } from '../api/trial'

export const useTrialStore = defineStore('trial', () => {
  const trialEnabled = ref<boolean | null>(null)
  const loading = ref(false)

  const isTrial = computed(() => trialEnabled.value === true)
  const isReady = computed(() => trialEnabled.value !== null)

  async function loadTrialStatus() {
    if (loading.value || trialEnabled.value !== null) return
    loading.value = true
    try {
      const res = await getTrialStatus()
      trialEnabled.value = res.data?.trialEnabled ?? false
    } catch {
      trialEnabled.value = false
    } finally {
      loading.value = false
    }
  }

  return { trialEnabled, loading, isTrial, isReady, loadTrialStatus }
})
