import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getTrialStatus } from '../api/trial'

export const useTrialStore = defineStore('trial', () => {
  const trialEnabled = ref<boolean | null>(null)
  const loading = ref(false)
  const statusUnavailable = ref(false)
  let statusRequest: Promise<void> | null = null

  const isTrial = computed(() => trialEnabled.value === true)
  const isReady = computed(() => trialEnabled.value !== null)

  function loadTrialStatus(retry = false): Promise<void> {
    if (trialEnabled.value !== null) return Promise.resolve()
    if (statusRequest) return statusRequest
    if (statusUnavailable.value && !retry) return Promise.resolve()

    statusUnavailable.value = false
    loading.value = true
    statusRequest = getTrialStatus()
      .then((res) => {
        trialEnabled.value = res.data.trialEnabled
      })
      .catch(() => {
        trialEnabled.value = null
        statusUnavailable.value = true
      })
      .finally(() => {
        loading.value = false
        statusRequest = null
      })
    return statusRequest
  }

  return { trialEnabled, loading, statusUnavailable, isTrial, isReady, loadTrialStatus }
})
