import request from './request'
import type {
  R,
  ModelProviderVO,
  UserModelConfigVO,
  UserModelConfigRequest,
  ContextWindowLookupVO,
  ContextWindowLookupRequest,
} from '../types'

export function getModelProviders() {
  return request.get<unknown, R<ModelProviderVO[]>>('/model-config/providers')
}

export function getModelConfigs() {
  return request.get<unknown, R<UserModelConfigVO[]>>('/model-config/configs')
}

export function createModelConfig(data: UserModelConfigRequest) {
  return request.post<unknown, R<UserModelConfigVO>>('/model-config/configs', data)
}

export function updateModelConfig(id: number, data: UserModelConfigRequest) {
  return request.put<unknown, R<UserModelConfigVO>>(`/model-config/configs/${id}`, data)
}

export function deleteModelConfig(id: number) {
  return request.delete<unknown, R<null>>(`/model-config/configs/${id}`)
}

export function setDefaultModelConfig(id: number) {
  return request.put<unknown, R<null>>(`/model-config/configs/${id}/default`)
}

export function getActiveModelConfig() {
  return request.get<unknown, R<UserModelConfigVO>>('/model-config/active')
}

export function lookupContextWindow(data: ContextWindowLookupRequest) {
  return request.post<unknown, R<ContextWindowLookupVO>>('/model-config/context-window/lookup', data)
}

export function lookupSavedConfigContextWindow(id: number) {
  return request.get<unknown, R<ContextWindowLookupVO>>(`/model-config/configs/${id}/context-window`)
}
