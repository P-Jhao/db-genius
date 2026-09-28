import request from './request'
import type { R, UploadedFile } from '../types'

export function uploadFile(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post<unknown, R<UploadedFile>>('/file/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
