<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message, Modal } from '@arco-design/web-vue'
import type { DbConfigVO, DbConfigRequest } from '../../types'
import { useTrialStore } from '../../stores/trial'
import {
  getDbConfigs,
  createDbConfig,
  updateDbConfig,
  deleteDbConfig,
  testDbConfig,
  getDoc,
} from '../../api/dbConfig'

const { t } = useI18n()
const trialStore = useTrialStore()
const configs = ref<DbConfigVO[]>([])
const loading = ref(false)
const modalVisible = ref(false)
const modalLoading = ref(false)
const editingId = ref<number | null>(null)
const docDrawer = ref(false)
const currentDoc = ref('')
const currentDocName = ref('')
const docLoading = ref(false)

const isTrial = computed(() => trialStore.isTrial)

const form = reactive<DbConfigRequest>({
  name: '',
  dbType: 'mysql',
  host: '',
  port: 3306,
  dbName: '',
  username: '',
  password: '',
})

function resetForm() {
  form.name = ''
  form.dbType = 'mysql'
  form.host = ''
  form.port = 3306
  form.dbName = ''
  form.username = ''
  form.password = ''
}

async function loadConfigs() {
  loading.value = true
  try {
    const res = await getDbConfigs()
    configs.value = res.data
  } catch (err: unknown) {
    Message.error((err as Error).message || t('admin.dbConfig.loadFailed'))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  resetForm()
  modalVisible.value = true
}

function openEdit(config: DbConfigVO) {
  editingId.value = config.id
  form.name = config.name
  form.dbType = config.dbType
  form.host = config.host
  form.port = config.port
  form.dbName = config.dbName
  form.username = config.username
  form.password = ''
  modalVisible.value = true
}

async function handleSubmit() {
  if (!form.name || !form.host || !form.dbName || !form.username || !form.password) {
    Message.warning(t('admin.dbConfig.fillAllFields'))
    return
  }
  modalLoading.value = true
  try {
    if (editingId.value) {
      await updateDbConfig(editingId.value, form)
      Message.success(t('admin.dbConfig.updateSuccess'))
    } else {
      await createDbConfig(form)
      Message.success(t('admin.dbConfig.createSuccess'))
    }
    modalVisible.value = false
    await loadConfigs()
  } catch (err: unknown) {
    Message.error((err as Error).message || t('admin.dbConfig.operateFailed'))
  } finally {
    modalLoading.value = false
  }
}

function handleDelete(config: DbConfigVO) {
  Modal.warning({
    title: t('admin.dbConfig.deleteConfirmTitle'),
    content: t('admin.dbConfig.deleteConfirmContent', { name: config.name }),
    okText: t('admin.dbConfig.deleteText'),
    okButtonProps: { status: 'danger' },
    async onOk() {
      try {
        await deleteDbConfig(config.id)
        Message.success(t('admin.dbConfig.deleteSuccess'))
        await loadConfigs()
      } catch (err: unknown) {
        Message.error((err as Error).message || t('admin.dbConfig.deleteFailed'))
      }
    },
  })
}

async function handleTest(config: DbConfigVO) {
  try {
    const res = await testDbConfig(config.id)
    if (res.data) {
      Message.success(t('admin.dbConfig.testOk'))
    } else {
      Message.error(t('admin.dbConfig.testBad'))
    }
    await loadConfigs()
  } catch (err: unknown) {
    Message.error((err as Error).message || t('admin.dbConfig.testFailed'))
  }
}

async function handleViewDoc(config: DbConfigVO) {
  currentDocName.value = config.name
  docLoading.value = true
  docDrawer.value = true
  try {
    const res = await getDoc(config.id)
    currentDoc.value = res.data || t('admin.dbConfig.docEmpty')
  } catch (err: unknown) {
    currentDoc.value = (err as Error).message || t('admin.dbConfig.docFailed')
  } finally {
    docLoading.value = false
  }
}

function getStatusType(status: number): 'warning' | 'success' | 'danger' {
  if (status === 0) return 'warning'
  if (status === 1) return 'success'
  return 'danger'
}

function getStatusIcon(status: number): string {
  if (status === 0) return 'icon-loading'
  if (status === 1) return 'icon-check-circle'
  return 'icon-close-circle'
}

onMounted(() => {
  trialStore.loadTrialStatus()
  loadConfigs()
})
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2>{{ $t('admin.dbConfig.title') }}</h2>
        <p class="page-desc">
          {{ isTrial ? $t('admin.dbConfig.descTrial') : $t('admin.dbConfig.desc') }}
        </p>
      </div>
      <a-button v-if="!isTrial" type="primary" @click="openCreate">
        <template #icon><icon-plus /></template>
        {{ $t('admin.dbConfig.create') }}
      </a-button>
    </div>

    <a-spin :loading="loading" style="width: 100%">
      <div class="config-grid">
        <a-card v-for="config in configs" :key="config.id" class="config-card" :bordered="false">
          <div class="config-card-header">
            <div class="config-name">
              <icon-storage class="config-icon" />
              <span>{{ config.name }}</span>
            </div>
            <a-badge
              :status="getStatusType(config.status)"
              :text="config.statusDesc"
            />
          </div>
          <div class="config-info">
            <div class="info-row">
              <span class="label">{{ $t('admin.dbConfig.labelHost') }}</span>
              <span class="value">{{ config.host }}:{{ config.port }}</span>
            </div>
            <div class="info-row">
              <span class="label">{{ $t('admin.dbConfig.labelDb') }}</span>
              <span class="value">{{ config.dbName }}</span>
            </div>
            <div class="info-row">
              <span class="label">{{ $t('admin.dbConfig.labelUser') }}</span>
              <span class="value">{{ config.username }}</span>
            </div>
            <div class="info-row">
              <span class="label">{{ $t('admin.dbConfig.labelType') }}</span>
              <a-tag size="small" color="arcoblue">{{ config.dbType }}</a-tag>
            </div>
          </div>
          <div class="config-actions">
            <a-button v-if="!isTrial" size="small" type="text" @click="handleTest(config)">
              <template #icon><icon-sync /></template>
              {{ $t('admin.dbConfig.test') }}
            </a-button>
            <a-button size="small" type="text" @click="handleViewDoc(config)">
              <template #icon><icon-file /></template>
              {{ $t('admin.dbConfig.doc') }}
            </a-button>
            <a-button v-if="!isTrial" size="small" type="text" @click="openEdit(config)">
              <template #icon><icon-edit /></template>
              {{ $t('admin.dbConfig.edit') }}
            </a-button>
            <a-button v-if="!isTrial" size="small" type="text" status="danger" @click="handleDelete(config)">
              <template #icon><icon-delete /></template>
              {{ $t('admin.dbConfig.delete') }}
            </a-button>
          </div>
        </a-card>

        <a-card v-if="configs.length === 0 && !loading" class="config-card empty-card">
          <a-empty :description="$t('admin.dbConfig.emptyDesc')">
            <template #image>
              <icon-storage :size="48" :style="{ color: 'var(--color-text-4)' }" />
            </template>
            <a-button v-if="!isTrial" type="primary" @click="openCreate">{{ $t('admin.dbConfig.addConfig') }}</a-button>
          </a-empty>
        </a-card>
      </div>
    </a-spin>

    <a-modal
      v-model:visible="modalVisible"
      :title="editingId ? $t('admin.dbConfig.modalEditTitle') : $t('admin.dbConfig.modalCreateTitle')"
      :ok-loading="modalLoading"
      @ok="handleSubmit"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item :label="$t('admin.dbConfig.fieldName')" required>
          <a-input v-model="form.name" :placeholder="$t('admin.dbConfig.fieldNamePlaceholder')" />
        </a-form-item>
        <a-row :gutter="16">
          <a-col :span="16">
            <a-form-item :label="$t('admin.dbConfig.fieldHost')" required>
              <a-input v-model="form.host" placeholder="192.168.1.100" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item :label="$t('admin.dbConfig.fieldPort')" required>
              <a-input-number v-model="form.port" :min="1" :max="65535" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item :label="$t('admin.dbConfig.fieldDbName')" required>
          <a-input v-model="form.dbName" placeholder="my_database" />
        </a-form-item>
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item :label="$t('admin.dbConfig.fieldUsername')" required>
              <a-input v-model="form.username" placeholder="root" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item :label="$t('admin.dbConfig.fieldPassword')" required>
              <a-input-password v-model="form.password" :placeholder="$t('admin.dbConfig.fieldPasswordPlaceholder')" />
            </a-form-item>
          </a-col>
        </a-row>
      </a-form>
    </a-modal>

    <a-drawer
      v-model:visible="docDrawer"
      :title="$t('admin.dbConfig.docDrawerTitle', { name: currentDocName })"
      :width="600"
      :footer="false"
    >
      <a-spin :loading="docLoading" style="width: 100%">
        <div class="doc-content">
          <pre>{{ currentDoc }}</pre>
        </div>
      </a-spin>
    </a-drawer>
  </div>
</template>

<style scoped lang="scss">
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 24px;

  h2 {
    font-size: 20px;
    font-weight: 600;
    margin-bottom: 4px;
  }

  .page-desc {
    font-size: 13px;
    color: var(--color-text-3);
  }
}

.config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}

.config-card {
  border-radius: 12px;
  border: 1px solid var(--color-border-1);
  transition: box-shadow 0.2s;

  &:hover {
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
  }
}

.empty-card {
  grid-column: 1 / -1;
}

.config-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.config-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;

  .config-icon {
    color: rgb(var(--primary-6));
  }
}

.config-info {
  margin-bottom: 16px;

  .info-row {
    display: flex;
    align-items: center;
    padding: 4px 0;

    .label {
      width: 56px;
      font-size: 13px;
      color: var(--color-text-3);
      flex-shrink: 0;
    }

    .value {
      font-size: 13px;
      color: var(--color-text-1);
      word-break: break-all;
    }
  }
}

.config-actions {
  display: flex;
  gap: 4px;
  border-top: 1px solid var(--color-border-1);
  padding-top: 12px;
}

.doc-content {
  pre {
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 13px;
    line-height: 1.6;
    font-family: 'SF Mono', Monaco, Menlo, Consolas, monospace;
    color: var(--color-text-2);
  }
}

@media (max-width: 768px) {
  .config-grid {
    grid-template-columns: 1fr;
  }

  .page-header {
    flex-direction: column;
    gap: 12px;
  }
}
</style>
