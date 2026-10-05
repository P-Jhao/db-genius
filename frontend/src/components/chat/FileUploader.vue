<script setup lang="ts">
import { computed, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { uploadFile } from '../../api/file'
import type { UploadedFile } from '../../types'
import { useTrialStore } from '../../stores/trial'

const SUPPORTED_FILE_EXTENSIONS = [
  '.xlsx', '.xls', '.csv', '.docx', '.pdf', '.md',
  '.png', '.jpg', '.jpeg', '.webp', '.bmp',
] as const
const EXCEL_FILE_EXTENSIONS = ['.xlsx', '.xls'] as const
const trialStore = useTrialStore()
const allowedFileExtensions = computed(() => trialStore.isReady && !trialStore.isTrial
  ? SUPPORTED_FILE_EXTENSIONS : EXCEL_FILE_EXTENSIONS)
const supportedFileExtensions = computed(() => new Set<string>(allowedFileExtensions.value))
const maximumFileSizeBytes = 20 * 1024 * 1024

const { t } = useI18n()

const uploadedFiles = ref<UploadedFile[]>([])
const uploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const emit = defineEmits<{
  filesChanged: [files: UploadedFile[]]
}>()

function triggerUpload() {
  fileInput.value?.click()
}

async function handleUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  const extensionSeparator = file.name.lastIndexOf('.')
  const extension = extensionSeparator < 0 ? '' : file.name.slice(extensionSeparator).toLowerCase()
  if (!supportedFileExtensions.value.has(extension)) {
    Message.warning(t('chat.uploader.unsupportedType', {
      extensions: allowedFileExtensions.value.join(', '),
    }))
    input.value = ''
    return
  }

  if (file.size > maximumFileSizeBytes) {
    Message.warning(t('chat.uploader.sizeLimit'))
    input.value = ''
    return
  }

  uploading.value = true
  try {
    const res = await uploadFile(file)
    uploadedFiles.value.push(res.data)
    emit('filesChanged', [...uploadedFiles.value])
    Message.success(t('chat.uploader.success'))
  } catch (err: unknown) {
    Message.error(getUploadErrorMessage(err))
  } finally {
    uploading.value = false
    input.value = ''
  }
}

function removeFile(id: number) {
  uploadedFiles.value = uploadedFiles.value.filter((f) => f.id !== id)
  emit('filesChanged', [...uploadedFiles.value])
}

function getUploadErrorMessage(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = error.response
    if (typeof response === 'object' && response !== null && 'data' in response) {
      const data = response.data
      if (typeof data === 'object' && data !== null) {
        if ('message' in data && typeof data.message === 'string' && data.message.trim()) {
          return data.message
        }
        if ('detail' in data && typeof data.detail === 'string' && data.detail.trim()) {
          return data.detail
        }
      }
    }
  }
  if (error instanceof Error && error.message.trim()) return error.message
  if (typeof error === 'string' && error.trim()) return error
  return t('chat.uploader.failed')
}

function formatSize(bytes: number | null): string {
  if (bytes === null) return '—'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}
</script>

<template>
  <div class="file-uploader">
    <div class="file-list">
      <a-tag
        v-for="file in uploadedFiles"
        :key="file.id"
        closable
        color="arcoblue"
        size="medium"
        @close="removeFile(file.id)"
      >
        <icon-file style="margin-right: 4px" />
        {{ file.originalName }} ({{ formatSize(file.fileSize) }})
      </a-tag>
    </div>
    <div class="upload-btn" :class="{ uploading }">
      <input
        ref="fileInput"
        type="file"
        :accept="allowedFileExtensions.join(',')"
        @change="handleUpload"
      />
      <a-button size="small" :loading="uploading" :disabled="uploading" @click="triggerUpload">
        <template #icon><icon-plus /></template>
        {{ $t('chat.uploader.button') }}
      </a-button>
    </div>
  </div>
</template>

<style scoped lang="scss">
.file-uploader {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.file-list {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.upload-btn {
  cursor: pointer;

  input[type="file"] {
    display: none;
  }

  &.uploading {
    pointer-events: none;
    opacity: 0.6;
  }
}
</style>
