import axios from 'axios'
import { getCurrentLocale } from '../i18n'
import type { R, TrialStatus } from '../types'

const baseUrl = import.meta.env.VITE_API_BASE_URL

/**
 * 查询当前是否为开源版部署。
 * 该接口用于未登录页面（首页、登录页）的判断，因此使用原生 axios，
 * 避免触发认证拦截导致的跳转。
 */
export function getTrialStatus() {
  return axios
    .get<R<TrialStatus>>(`${baseUrl}/trial/status`, {
      headers: { 'Accept-Language': getCurrentLocale() },
    })
    .then((res) => res.data)
}
