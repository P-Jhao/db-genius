import request from './request'
import type { R, LoginRequest, LoginVO } from '../types'

export function login(data: LoginRequest) {
  return request.post<unknown, R<LoginVO>>('/auth/login', data)
}

export function logout() {
  return request.post<unknown, R<null>>('/auth/logout')
}
