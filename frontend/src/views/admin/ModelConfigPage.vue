<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message, Modal } from '@arco-design/web-vue'
import type { ModelProviderVO, UserModelConfigVO, UserModelConfigRequest } from '../../types'
import { useTrialStore } from '../../stores/trial'
import GitHubIcon from '../../components/common/GitHubIcon.vue'
import { GITHUB_REPO_URL } from '../../config/site'
import {
  getModelProviders,
  getModelConfigs,
  createModelConfig,
  updateModelConfig,
  deleteModelConfig,
  setDefaultModelConfig,
  getActiveModelConfig,
  lookupContextWindow,
  lookupSavedConfigContextWindow,
} from '../../api/modelConfig'

const { t, locale } = useI18n()
const trialStore = useTrialStore()
const isTrial = computed(() => trialStore.isTrial)

const configs = ref<UserModelConfigVO[]>([])
const providers = ref<ModelProviderVO[]>([])
const activeConfig = ref<UserModelConfigVO | null>(null)
const loading = ref(false)
const activeLoading = ref(false)
const activeError = ref(false)
const modalVisible = ref(false)
const modalLoading = ref(false)
const editingId = ref<number | null>(null)

interface ModelForm {
  providerCode: string
  displayName: string
  baseUrl: string
  apiKey: string
  modelName: string
  contextWindow: number | undefined
}

const form = reactive<ModelForm>({
  providerCode: '',
  displayName: '',
  baseUrl: '',
  apiKey: '',
  modelName: '',
  contextWindow: undefined,
})

const lookupLoading = ref(false)

const sortedProviders = computed(() =>
  [...providers.value].sort((a, b) => a.sortOrder - b.sortOrder)
)

const selectedProvider = computed(() =>
  providers.value.find((p) => p.providerCode === form.providerCode)
)

function resetForm() {
  form.providerCode = ''
  form.displayName = ''
  form.baseUrl = ''
  form.apiKey = ''
  form.modelName = ''
  form.contextWindow = undefined
}

async function loadConfigs() {
  loading.value = true
  try {
    const [providerRes, configRes] = await Promise.all([
      getModelProviders(),
      getModelConfigs(),
    ])
    providers.value = providerRes.data
    configs.value = configRes.data
  } catch (err: unknown) {
    Message.error((err as Error).message || t('admin.modelConfig.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function loadActive() {
  activeLoading.value = true
  activeError.value = false
  try {
    const res = await getActiveModelConfig()
    activeConfig.value = res.data
  } catch {
    activeError.value = true
  } finally {
    activeLoading.value = false
  }
}

function openCreate() {
  editingId.value = null
  resetForm()
  const first = sortedProviders.value[0]
  if (first) {
    form.providerCode = first.providerCode
    form.baseUrl = first.defaultBaseUrl || ''
    form.modelName = first.defaultModel || ''
  }
  modalVisible.value = true
}

function openEdit(config: UserModelConfigVO) {
  editingId.value = config.id
  form.providerCode = config.providerCode
  form.displayName = config.displayName
  form.baseUrl = config.baseUrl
  form.apiKey = ''
  form.modelName = config.modelName
  form.contextWindow = config.contextWindow ?? undefined
  modalVisible.value = true
}

/**
 * 远程获取上下文窗口：新建/已填 apiKey 走 lookup 接口；
 * 编辑且 apiKey 留空则用已保存配置的密钥查询。
 */
async function handleFetchContextWindow() {
  if (!form.modelName) {
    Message.warning(t('admin.modelConfig.warnModelName'))
    return
  }
  lookupLoading.value = true
  try {
    const res =
      form.apiKey || !editingId.value
        ? await lookupContextWindow({
            baseUrl: form.baseUrl || selectedProvider.value?.defaultBaseUrl || '',
            apiKey: form.apiKey,
            modelName: form.modelName,
          })
        : await lookupSavedConfigContextWindow(editingId.value)
    const data = res.data
    if (data.contextWindow != null) {
      form.contextWindow = data.contextWindow
      Message.success(t('admin.modelConfig.contextDetected', { count: data.contextWindow.toLocaleString() }))
    } else {
      Message.warning(t('admin.modelConfig.contextNotDetected'))
    }
  } catch (err: unknown) {
    Message.error((err as Error).message || t('admin.modelConfig.fetchFailed'))
  } finally {
    lookupLoading.value = false
  }
}

function handleProviderChange(code: unknown) {
  if (typeof code !== 'string') return
  const provider = providers.value.find((p) => p.providerCode === code)
  if (!provider) return
  form.baseUrl = provider.defaultBaseUrl || ''
  form.modelName = provider.defaultModel || ''
}

async function handleSubmit() {
  if (!form.providerCode || !form.displayName || !form.modelName) {
    Message.warning(t('admin.modelConfig.fillAllFields'))
    return
  }
  if (form.providerCode === 'custom' && !form.baseUrl) {
    Message.warning(t('admin.modelConfig.customBaseUrlRequired'))
    return
  }
  if (!editingId.value && !form.apiKey) {
    Message.warning(t('admin.modelConfig.apiKeyRequired'))
    return
  }
  modalLoading.value = true
  try {
    const provider = selectedProvider.value
    const payload: UserModelConfigRequest = {
      providerCode: form.providerCode,
      providerType: provider?.providerType || 'openai_compatible',
      displayName: form.displayName,
      baseUrl: form.baseUrl || undefined,
      apiKey: form.apiKey,
      modelName: form.modelName,
      contextWindow: form.contextWindow ?? undefined,
    }
    if (editingId.value) {
      await updateModelConfig(editingId.value, payload)
      Message.success(t('admin.modelConfig.updateSuccess'))
    } else {
      await createModelConfig(payload)
      Message.success(t('admin.modelConfig.createSuccess'))
    }
    modalVisible.value = false
    await loadConfigs()
  } catch (err: unknown) {
    Message.error((err as Error).message || t('admin.modelConfig.operateFailed'))
  } finally {
    modalLoading.value = false
  }
}

function handleDelete(config: UserModelConfigVO) {
  Modal.warning({
    title: t('admin.modelConfig.deleteConfirmTitle'),
    content: t('admin.modelConfig.deleteConfirmContent', { name: config.displayName }),
    okText: t('admin.modelConfig.deleteText'),
    okButtonProps: { status: 'danger' },
    async onOk() {
      try {
        await deleteModelConfig(config.id as number)
        Message.success(t('admin.modelConfig.deleteSuccess'))
        await loadConfigs()
      } catch (err: unknown) {
        Message.error((err as Error).message || t('admin.modelConfig.deleteFailed'))
      }
    },
  })
}

async function handleSetDefault(config: UserModelConfigVO) {
  try {
    await setDefaultModelConfig(config.id as number)
    Message.success(t('admin.modelConfig.setDefaultSuccess'))
    await loadConfigs()
  } catch (err: unknown) {
    Message.error((err as Error).message || t('admin.modelConfig.operateFailed'))
  }
}

function formatTime(dateStr: string) {
  return new Date(dateStr).toLocaleString(locale.value)
}

onMounted(async () => {
  await trialStore.loadTrialStatus()
  if (trialStore.isTrial) {
    loadActive()
  } else {
    loadConfigs()
  }
})
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2>{{ $t('admin.modelConfig.title') }}</h2>
        <p class="page-desc">
          <template v-if="isTrial">
            {{ $t('admin.modelConfig.descTrial') }}
            <a-link v-if="GITHUB_REPO_URL" :href="GITHUB_REPO_URL" target="_blank">
              <GitHubIcon :size="13" /> {{ $t('admin.modelConfig.sourceCode') }}
            </a-link>
          </template>
          <template v-else>
            {{ $t('admin.modelConfig.desc') }}
          </template>
        </p>
      </div>
      <a-button v-if="!isTrial" type="primary" @click="openCreate">
        <template #icon><icon-plus /></template>
        {{ $t('admin.modelConfig.create') }}
      </a-button>
    </div>

    <!-- 开源版：只读展示系统内置模型 -->
    <a-spin v-if="isTrial" :loading="activeLoading" style="width: 100%">
      <div class="config-grid">
        <a-card v-if="activeConfig" class="config-card" :bordered="false">
          <div class="config-card-header">
            <div class="config-name">
              <icon-robot class="config-icon" />
              <span>{{ activeConfig.displayName || $t('admin.modelConfig.builtinName') }}</span>
            </div>
            <a-tag color="arcoblue">{{ $t('admin.modelConfig.builtinTag') }}</a-tag>
          </div>
          <div class="config-info">
            <div class="info-row">
              <span class="label">{{ $t('admin.modelConfig.labelApiUrl') }}</span>
              <span class="value">{{ activeConfig.baseUrl }}</span>
            </div>
            <div class="info-row">
              <span class="label">{{ $t('admin.modelConfig.labelModel') }}</span>
              <span class="value">{{ activeConfig.modelName }}</span>
            </div>
          </div>
        </a-card>
        <a-card v-else-if="!activeLoading && activeError" class="config-card empty-card">
          <a-empty :description="$t('admin.modelConfig.emptyActive')" />
        </a-card>
      </div>
    </a-spin>

    <!-- 正式版：配置列表 -->
    <a-spin v-else :loading="loading" style="width: 100%">
      <div class="config-grid">
        <a-card v-for="config in configs" :key="config.id ?? config.displayName" class="config-card" :bordered="false">
          <div class="config-card-header">
            <div class="config-name">
              <icon-robot class="config-icon" />
              <span>{{ config.displayName }}</span>
              <a-tag v-if="config.isDefault" size="small" color="arcoblue">{{ $t('admin.modelConfig.defaultTag') }}</a-tag>
            </div>
            <a-badge
              :status="config.status === 1 ? 'success' : 'warning'"
              :text="config.statusDesc"
            />
          </div>
          <div class="config-info">
            <div class="info-row">
              <span class="label">{{ $t('admin.modelConfig.labelProvider') }}</span>
              <a-tag size="small">{{ config.providerCode }}</a-tag>
            </div>
            <div class="info-row">
              <span class="label">{{ $t('admin.modelConfig.labelApiUrl') }}</span>
              <span class="value">{{ config.baseUrl }}</span>
            </div>
            <div class="info-row">
              <span class="label">{{ $t('admin.modelConfig.labelModel') }}</span>
              <span class="value">{{ config.modelName }}</span>
            </div>
            <div class="info-row">
              <span class="label">{{ $t('admin.modelConfig.labelContextWindow') }}</span>
              <span class="value">
                {{ config.contextWindow ? config.contextWindow.toLocaleString() + ' tokens' : $t('admin.modelConfig.notSet') }}
              </span>
            </div>
            <div class="info-row">
              <span class="label">{{ $t('admin.modelConfig.labelCreatedAt') }}</span>
              <span class="value">{{ formatTime(config.createdAt) }}</span>
            </div>
          </div>
          <div class="config-actions">
            <a-button v-if="!config.isDefault" size="small" type="text" @click="handleSetDefault(config)">
              <template #icon><icon-star /></template>
              {{ $t('admin.modelConfig.setDefault') }}
            </a-button>
            <a-button size="small" type="text" @click="openEdit(config)">
              <template #icon><icon-edit /></template>
              {{ $t('admin.modelConfig.edit') }}
            </a-button>
            <a-button size="small" type="text" status="danger" @click="handleDelete(config)">
              <template #icon><icon-delete /></template>
              {{ $t('admin.modelConfig.delete') }}
            </a-button>
          </div>
        </a-card>

        <a-card v-if="configs.length === 0 && !loading" class="config-card empty-card">
          <a-empty :description="$t('admin.modelConfig.emptyDesc')">
            <template #image>
              <icon-robot :size="48" :style="{ color: 'var(--color-text-4)' }" />
            </template>
            <a-button type="primary" @click="openCreate">{{ $t('admin.modelConfig.addConfig') }}</a-button>
          </a-empty>
        </a-card>
      </div>
    </a-spin>

    <a-modal
      v-model:visible="modalVisible"
      :title="editingId ? $t('admin.modelConfig.modalEditTitle') : $t('admin.modelConfig.modalCreateTitle')"
      :ok-loading="modalLoading"
      @ok="handleSubmit"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item :label="$t('admin.modelConfig.fieldProvider')" required>
          <a-select v-model="form.providerCode" :disabled="!!editingId" @change="handleProviderChange">
            <a-option v-for="p in sortedProviders" :key="p.providerCode" :value="p.providerCode">
              {{ p.displayName }}
            </a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="$t('admin.modelConfig.fieldName')" required>
          <a-input v-model="form.displayName" :placeholder="$t('admin.modelConfig.fieldNamePlaceholder')" />
        </a-form-item>
        <a-form-item :label="$t('admin.modelConfig.fieldBaseUrl')" :required="form.providerCode === 'custom'">
          <a-input v-model="form.baseUrl" :placeholder="$t('admin.modelConfig.fieldBaseUrlPlaceholder')" />
        </a-form-item>
        <a-form-item :label="$t('admin.modelConfig.fieldApiKey')" :required="!editingId">
          <a-input-password
            v-model="form.apiKey"
            :placeholder="editingId ? $t('admin.modelConfig.apiKeyPlaceholderEdit') : 'sk-xxxx'"
          />
        </a-form-item>
        <a-form-item :label="$t('admin.modelConfig.fieldModelName')" required>
          <a-input v-model="form.modelName" placeholder="deepseek-v4-pro" />
        </a-form-item>
        <a-form-item :label="$t('admin.modelConfig.fieldContextWindow')">
          <div class="context-window-row">
            <a-input-number
              v-model="form.contextWindow"
              :min="1024"
              :step="1024"
              :placeholder="$t('admin.modelConfig.contextWindowPlaceholder')"
              allow-clear
            />
            <a-button :loading="lookupLoading" @click="handleFetchContextWindow">
              <template #icon><icon-cloud-download /></template>
              {{ $t('admin.modelConfig.fetchRemote') }}
            </a-button>
          </div>
        </a-form-item>
      </a-form>
    </a-modal>
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
      width: 64px;
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

.context-window-row {
  display: flex;
  gap: 8px;
  width: 100%;

  :deep(.arco-input-number) {
    flex: 1;
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
