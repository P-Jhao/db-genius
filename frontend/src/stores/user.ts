import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { login as loginApi, logout as logoutApi } from '../api/auth'
import type { LoginRequest, LoginVO } from '../types'
import router from '../router'

export const useUserStore = defineStore('user', () => {
  const token = ref(localStorage.getItem('token') || '')
  const userInfo = ref<LoginVO | null>(
    localStorage.getItem('userInfo') ? JSON.parse(localStorage.getItem('userInfo')!) : null
  )

  const isLoggedIn = computed(() => !!token.value)
  const username = computed(() => userInfo.value?.username || '')
  const nickname = computed(() => userInfo.value?.nickname || '')
  const role = computed(() => userInfo.value?.role || '')

  async function login(req: LoginRequest) {
    const res = await loginApi(req)
    token.value = res.data.token
    userInfo.value = res.data
    localStorage.setItem('token', res.data.token)
    localStorage.setItem('userInfo', JSON.stringify(res.data))
  }

  function clearAuth() {
    token.value = ''
    userInfo.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('userInfo')
  }

  async function logout(redirectTo?: string) {
    try {
      await logoutApi()
    } finally {
      clearAuth()
      if (redirectTo) {
        router.push({ name: 'login', query: { redirect: redirectTo } })
      } else {
        router.push('/login')
      }
    }
  }

  return { token, userInfo, isLoggedIn, username, nickname, role, login, logout, clearAuth }
})
