import { useUserStore } from '../stores/user'
import router from '../router'

/**
 * 处理未授权（token 失效/过期）：清除本地登录态并跳转到登录页，
 * 同时携带当前路径作为 redirect，登录后可返回。
 */
export function handleUnauthorized(redirectPath?: string) {
  const userStore = useUserStore()
  const redirect = redirectPath ?? router.currentRoute.value.fullPath
  userStore.clearAuth()
  router.push({ name: 'login', query: { redirect } })
}
