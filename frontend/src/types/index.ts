export interface R<T> {
  code: number
  message: string
  data: T
}

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginVO {
  token: string
  username: string
  nickname: string
  role: string
}

export interface CreateUserRequest {
  username: string
  password: string
  nickname?: string
  role?: 'admin' | 'user'
}

export interface DbConfigRequest {
  name: string
  dbType?: string
  host: string
  port: number
  dbName: string
  username: string
  password: string
}

export interface DbConfigVO {
  id: number
  name: string
  dbType: string
  host: string
  port: number
  dbName: string
  username: string
  status: 0 | 1 | 2
  statusDesc: string
  docContent: string | null
  docGeneratedAt: string | null
  createdAt: string
}

export interface ConversationVO {
  id: number
  title: string
  type: IntentType
  dbConfigIds: string
  totalTokens?: number | null
  contextTokens?: number | null
  createdAt: string
}

export interface Message {
  id: number
  conversationId: number
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  step: number | null
  type:
    | 'user'
    | 'thinking'
    | 'reasoning'
    | 'sql'
    | 'result'
    | 'error'
    | 'file_parsed'
    | 'step'
    | 'summary'
    | 'done'
    | 'aborted'
    | 'compressed'
    | 'classifying'
    | 'classified'
    | 'clarify'
    | 'routing'
    | 'content'
    | 'tool'
    | null
  reasoningContent?: string | null
  toolCalls?: string | null
  fileUrl: string | null
  createdAt: string
}

export type IntentType = 'simple_chat' | 'sql_query' | 'workflow' | 'db_compare'

export interface UnifiedChatRequest {
  message: string
  conversationId?: number | null
  dbConfigIds?: number[] | null
  preDbConfigId?: number | null
  testDbConfigId?: number | null
  fileIds?: number[] | null
  confirmedIntent?: IntentType | null
}

export interface ClassifiedContent {
  intent: IntentType
  confidence: number
  reasoning: string
  needsClarification: boolean
}

export interface ClarifyOption {
  intent: IntentType
  label: string
}

export interface ClarifyContent {
  question: string
  options: ClarifyOption[]
  reasoning: string
}

export type SseEventType =
  | 'conversation'
  | 'classifying'
  | 'classified'
  | 'clarify'
  | 'routing'
  | 'thinking'
  | 'reasoning'
  | 'step'
  | 'content'
  | 'summary_delta'
  | 'summary'
  | 'error'
  | 'usage'
  | 'context_compact'
  | 'done'
  | 'aborted'

/** 单轮会话 token 用量（后端 usage 事件 content） */
export interface TokenUsageVO {
  promptTokens: number
  completionTokens: number
  totalTokens: number
  /** 当前上下文占用（最后一次 LLM 调用的 prompt_tokens） */
  contextTokens: number
  callCount: number
  conversationTotalTokens?: number | null
  contextWindow?: number | null
}

export interface ContextCompactContent {
  phase: 'start' | 'end'
  tier: 'elide' | 'summarize'
  message: string
  beforeTokens?: number | null
  afterTokens?: number | null
  affectedUnits?: number | null
}

/** 上下文压缩结果 */
export interface CompressResultVO {
  conversationId: number
  compressed: boolean
  beforeTokens: number | null
  afterTokens: number | null
  summaryMessageId: number | null
  message: string
}

/** 模型上下文窗口远程查询结果 */
export interface ContextWindowLookupVO {
  modelName: string
  contextWindow: number | null
  /** registry=内置注册表命中；not_found=未识别需手填 */
  source: string
}

export interface ContextWindowLookupRequest {
  baseUrl: string
  apiKey: string
  modelName: string
}

export interface SseEvent {
  taskId: string
  step: number
  type: SseEventType
  content: string | number | ClassifiedContent | ClarifyContent | TokenUsageVO | ContextCompactContent | null
  timestamp: number
}

export interface UploadedFile {
  id: number
  originalName: string
  fileSize: number | null
  contentType: string | null
  createdAt: string
}

export interface TrialStatus {
  trialEnabled: boolean
}

export interface ModelProviderVO {
  providerCode: string
  displayName: string
  providerType: string
  defaultBaseUrl: string | null
  defaultModel: string | null
  builtin: boolean
  sortOrder: number
}

export interface UserModelConfigVO {
  id: number | null
  providerCode: string
  providerType: string
  displayName: string
  baseUrl: string
  modelName: string
  /** 模型最大上下文窗口（token），未知为 null */
  contextWindow?: number | null
  isDefault: boolean
  status: 0 | 1
  statusDesc: string
  createdAt: string
}

export interface UserModelConfigRequest {
  providerCode: string
  providerType: string
  displayName: string
  baseUrl?: string
  apiKey: string
  modelName: string
  /** 留空则后端按已知模型注册表兜底 */
  contextWindow?: number | null
}
