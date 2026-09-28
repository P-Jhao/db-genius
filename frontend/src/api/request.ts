import axios from 'axios'
import { useUserStore } from '../stores/user'
import { handleUnauthorized } from '../utils/auth'
import { getCurrentLocale } from '../i18n'

const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 30000,
})

request.interceptors.request.use((config) => {
  const userStore = useUserStore()
  if (userStore.token) {
    config.headers.Authorization = userStore.token
  }
  // 后端按 Accept-Language 返回本地化文案（报错/SSE 事件等）
  config.headers['Accept-Language'] = getCurrentLocale()
  return config
})

request.interceptors.response.use(
  (response) => {
    const data = response.data
    if (data.code !== undefined && data.code !== 200) {
      if (data.code === 401) {
        handleUnauthorized()
      }
      return Promise.reject(new Error(data.message || 'Request failed'))
    }
    return data
  },
  (error) => {
    if (error.response?.status === 401) {
      handleUnauthorized()
    }
    return Promise.reject(error)
  }
)

export default request
