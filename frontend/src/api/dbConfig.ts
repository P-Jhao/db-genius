import request from './request'
import type { R, DbConfigRequest, DbConfigVO } from '../types'

export function getDbConfigs() {
  return request.get<unknown, R<DbConfigVO[]>>('/db-config')
}

export function getDbConfig(id: number) {
  return request.get<unknown, R<DbConfigVO>>(`/db-config/${id}`)
}

export function createDbConfig(data: DbConfigRequest) {
  return request.post<unknown, R<DbConfigVO>>('/db-config', data)
}

export function updateDbConfig(id: number, data: DbConfigRequest) {
  return request.put<unknown, R<DbConfigVO>>(`/db-config/${id}`, data)
}

export function deleteDbConfig(id: number) {
  return request.delete<unknown, R<null>>(`/db-config/${id}`)
}

export function testDbConfig(id: number) {
  return request.post<unknown, R<boolean>>(`/db-config/${id}/test`)
}

export function generateDoc(id: number) {
  return request.post<unknown, R<string>>(`/db-config/${id}/generate-doc`)
}

export function getDoc(id: number) {
  return request.get<unknown, R<string>>(`/db-config/${id}/doc`)
}
