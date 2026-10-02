import { createServer } from 'node:http'
import { once } from 'node:events'
import {
  activeModel, conversation, database, event, historyMessages, modelConfig, sseFrame, success, trialDatabase,
} from './s15-ui-data.mjs'

function setCorsHeaders(response) {
  response.setHeader('Access-Control-Allow-Origin', '*')
  response.setHeader('Access-Control-Allow-Headers', 'Authorization, Content-Type, Accept-Language')
  response.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
}

async function readBody(request) {
  const chunks = []
  for await (const chunk of request) chunks.push(Buffer.from(chunk))
  const raw = Buffer.concat(chunks).toString('utf8')
  if (!raw) return null
  return JSON.parse(raw)
}

function replyJson(response, status, body) {
  response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' })
  response.end(JSON.stringify(body))
}

function buildApiFixture() {
  let profile = 'standard'
  let trialStatusCalls = 0
  const requests = []
  const chatRequests = []
  const server = createServer((request, response) => {
    setCorsHeaders(response)
    if (request.method === 'OPTIONS') {
      response.writeHead(204)
      response.end()
      return
    }
    void handleRequest(request, response).catch((error) => {
      if (!response.headersSent) replyJson(response, 500, { message: String(error) })
      else response.destroy(error instanceof Error ? error : new Error(String(error)))
    })
  })

  async function handleRequest(request, response) {
    const url = new URL(request.url ?? '/', 'http://127.0.0.1')
    const body = await readBody(request)
    requests.push({ method: request.method ?? 'GET', path: url.pathname, body })
    const method = request.method ?? 'GET'
    const path = url.pathname

    if (path === '/api/trial/status') {
      const currentCall = trialStatusCalls
      trialStatusCalls += 1
      if (profile === 'trial-status-error' && currentCall === 0) {
        replyJson(response, 200, success({ trialEnabled: null }))
      } else {
        replyJson(response, 200, success({ trialEnabled: profile === 'trial' }))
      }
      return
    }
    if (path === '/api/auth/login' && method === 'POST') {
      replyJson(response, 200, success({
        token: 's15-fixture-token',
        username: 's15-reviewer',
        nickname: 'S15 Reviewer',
        role: 'admin',
      }))
      return
    }
    if (path === '/api/auth/logout') {
      replyJson(response, 200, success(null))
      return
    }
    if (path === '/api/db-config' && method === 'GET') {
      if (profile === 'error') {
        replyJson(response, 200, { code: 503, message: 'Fixture database unavailable', data: null })
      } else {
        const rows = profile === 'empty' ? [] : [profile === 'trial' ? trialDatabase : database]
        replyJson(response, 200, success(rows))
      }
      return
    }
    if (/^\/api\/db-config\/\d+\/doc$/.test(path)) {
      replyJson(response, 200, success(database.docContent))
      return
    }
    if (path.startsWith('/api/db-config/')) {
      replyJson(response, 200, success(null))
      return
    }
    if (path === '/api/model-config/providers') {
      replyJson(response, 200, success([
        { providerCode: 'openai', displayName: 'OpenAI', providerType: 'openai_compatible',
          defaultBaseUrl: 'https://api.openai.com/v1', defaultModel: 'gpt-4o', builtin: true, sortOrder: 1 },
        { providerCode: 'custom', displayName: 'Custom', providerType: 'openai_compatible',
          defaultBaseUrl: null, defaultModel: null, builtin: false, sortOrder: 99 },
      ]))
      return
    }
    if (path === '/api/model-config/configs') {
      replyJson(response, 200, success(profile === 'empty' ? [] : [modelConfig]))
      return
    }
    if (path === '/api/model-config/active') {
      replyJson(response, 200, success(activeModel))
      return
    }
    if (path.startsWith('/api/model-config/')) {
      replyJson(response, 200, success(null))
      return
    }
    if (path === '/api/chat/conversations') {
      replyJson(response, 200, success(profile === 'empty' ? [] : [conversation]))
      return
    }
    if (path === '/api/chat/conversations/42/messages') {
      replyJson(response, 200, success(historyMessages))
      return
    }
    if (path.startsWith('/api/chat/conversations/')) {
      replyJson(response, 200, success(null))
      return
    }
    if (path === '/api/chat' && method === 'POST') {
      await streamChat(response, body)
      return
    }
    replyJson(response, 404, { code: 404, message: `No fixture for ${method} ${path}`, data: null })
  }

  async function streamChat(response, body) {
    if (body === null || typeof body !== 'object' || Array.isArray(body)) {
      throw new Error('Expected a chat request object')
    }
    const chatCall = { body, clientAborted: false }
    chatRequests.push(chatCall)
    response.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
    })
    response.flushHeaders()
    let completed = false
    response.on('close', () => {
      chatCall.clientAborted = !completed
    })

    const send = async (events) => {
      for (const item of events) {
        if (response.destroyed) return
        response.write(sseFrame(item))
        await new Promise((resolve) => setTimeout(resolve, 20))
      }
    }

    if (typeof body.message === 'string' && body.message.startsWith('Hold response')) {
      await send([event('classifying', 'Classifying request'), event('thinking', 'Waiting for stop action', 2)])
      await new Promise((resolve) => response.once('close', resolve))
      return
    }

    if (body.confirmedIntent === 'sql_query') {
      await send([
        event('conversation', 42),
        event('classifying', 'Classifying request'),
        event('classified', { intent: 'sql_query', confidence: 0.99, reasoning: 'A database query was selected.', needsClarification: false }),
        event('routing', 'Routing to SQL query'),
        event('thinking', 'Preparing a read-only query', 2),
        event('step', 'SELECT COUNT(*) FROM accounts WHERE status = active', 3),
        event('summary_delta', 'The query found two active accounts.', 4),
        event('summary', 'The query found two active accounts.', 4),
        event('done', null, 4),
      ])
    } else {
      await send([
        event('conversation', 42),
        event('classifying', 'Classifying request'),
        event('classified', { intent: 'sql_query', confidence: 0.42, reasoning: 'The target is unclear.', needsClarification: true }),
        event('clarify', {
          question: 'Which kind of result do you want?',
          reasoning: 'The request could describe a database query or a general question.',
          options: [
            { intent: 'sql_query', label: 'SQL query' },
            { intent: 'simple_chat', label: 'General question' },
          ],
        }, 2),
        event('done', null, 2),
      ])
    }

    if (!response.destroyed) {
      completed = true
      response.end()
    }
  }

  return {
    async start() {
      server.listen(0, '127.0.0.1')
      await once(server, 'listening')
      const address = server.address()
      if (typeof address !== 'object' || address === null) throw new Error('API fixture did not bind a port')
      return { url: `http://127.0.0.1:${address.port}/api` }
    },
    setProfile(nextProfile) {
      profile = nextProfile
    },
    reset() {
      profile = 'standard'
      trialStatusCalls = 0
      requests.length = 0
      chatRequests.length = 0
    },
    get requests() {
      return requests
    },
    get chatRequests() {
      return chatRequests
    },
    async close() {
      server.close()
      await once(server, 'close')
    },
  }
}

export { buildApiFixture }
