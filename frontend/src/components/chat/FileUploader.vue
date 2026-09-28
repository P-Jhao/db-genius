<script setup lang="ts">
import { ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { uploadFile } from '../../api/file'
import type { UploadedFile } from '../../types'

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

  const validTypes = [
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-excel',
  ]
  if (!validTypes.includes(file.type) && !file.name.match(/\.xlsx?$/i)) {
    Message.warning(t('chat.uploader.excelOnly'))
    input.value = ''
    return
  }

  if (file.size > 50 * 1024 * 1024) {
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
    Message.error((err as Error).message || t('chat.uploader.failed'))
  } finally {
    uploading.value = false
    input.value = ''
  }
}

function removeFile(id: number) {
  uploadedFiles.value = uploadedFiles.value.filter((f) => f.id !== id)
  emit('filesChanged', [...uploadedFiles.value])
}

function formatSize(bytes: number): string {
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
      <input ref="fileInput" type="file" accept=".xlsx,.xls" @change="handleUpload" />
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
