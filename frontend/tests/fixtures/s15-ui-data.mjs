const FIXED_TIME = Date.parse('2026-09-30T08:00:00.000Z')

const database = {
  id: 1,
  name: 'Analytics Fixture',
  dbType: 'postgresql',
  host: 'db.fixture.invalid',
  port: 5432,
  dbName: 'analytics_fixture',
  username: 'fixture_reader',
  status: 1,
  statusDesc: 'Connected',
  docContent: 'Fixture schema: accounts(id, status).',
  docGeneratedAt: '2026-09-30T08:00:00.000Z',
  createdAt: '2026-09-30T07:00:00.000Z',
}

const trialDatabase = {
  ...database,
  name: 'Built-in Test Database',
  host: '',
  port: 0,
  dbName: '',
  username: '',
  docContent: null,
  docGeneratedAt: null,
}

const conversation = {
  id: 42,
  title: 'Quarterly account totals',
  type: 'sql_query',
  dbConfigIds: '1',
  totalTokens: 18,
  contextTokens: 18,
  createdAt: '2026-09-30T08:00:00.000Z',
}

const historyMessages = [
  {
    id: 101,
    conversationId: 42,
    role: 'user',
    content: 'Count active accounts.',
    step: null,
    type: 'user',
    reasoningContent: null,
    toolCalls: null,
    fileUrl: null,
    createdAt: '2026-09-30T08:00:00.000Z',
  },
  {
    id: 102,
    conversationId: 42,
    role: 'assistant',
    content: 'There are 2 active accounts.',
    step: 2,
    type: 'summary',
    reasoningContent: 'Count rows where status is active.',
    toolCalls: null,
    fileUrl: null,
    createdAt: '2026-09-30T08:00:01.000Z',
  },
]

const modelConfig = {
  id: 5,
  providerCode: 'custom',
  providerType: 'openai_compatible',
  displayName: 'Fixture Model',
  baseUrl: 'https://model.fixture.invalid/v1',
  modelName: 'fixture-llm',
  contextWindow: 8192,
  isDefault: true,
  status: 1,
  statusDesc: 'Enabled',
  createdAt: '2026-09-30T08:00:00.000Z',
}

const activeModel = { ...modelConfig, id: null, displayName: 'Built-in Fixture Model' }

function success(data) {
  return { code: 200, message: 'success', data }
}

function event(type, content, step = 1) {
  return {
    taskId: 's15-ui-task',
    step,
    type,
    content,
    timestamp: FIXED_TIME + step * 1000,
  }
}

function sseFrame(value) {
  return `data: ${JSON.stringify(value)}\n\n`
}

export { activeModel, conversation, database, event, historyMessages, modelConfig, sseFrame, success, trialDatabase }
