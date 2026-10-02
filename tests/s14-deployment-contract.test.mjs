import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = (path) => readFileSync(resolve(root, path), 'utf8')

test('Nginx routes API traffic to 8109 and preserves SSE disconnect behaviour', () => {
  const nginx = read('frontend/nginx.conf')
  assert.match(nginx, /proxy_pass\s+http:\/\/api:8109;/)
  assert.match(nginx, /proxy_buffering\s+off;/)
  assert.match(nginx, /proxy_ignore_client_abort\s+off;/)
  assert.match(nginx, /proxy_http_version\s+1\.1;/)
  assert.match(nginx, /proxy_set_header\s+Connection\s+'';/)
  assert.match(nginx, /proxy_request_buffering\s+off;/)
  assert.match(nginx, /proxy_cache\s+off;/)
  assert.match(nginx, /proxy_send_timeout\s+3600s;/)
  assert.match(nginx, /proxy_read_timeout\s+3600s;/)
  assert.match(nginx, /client_max_body_size\s+21m;/)
  assert.ok(21 * 1024 * 1024 > 20 * 1024 * 1024 + 1)
  assert.match(nginx, /\$uri/)
  assert.doesNotMatch(nginx, /\$request_uri|\$args/)
})

test('deployment stack gates API and worker startup on successful migration', () => {
  const compose = read('docker-compose.yml')
  assert.match(compose, /command:\s*\["alembic",\s*"upgrade",\s*"head"\]/)
  assert.equal((compose.match(/condition: service_completed_successfully/g) ?? []).length, 4)
  assert.match(compose, /POSTGRES_PASSWORD:.*\$\{POSTGRES_PASSWORD/)
  assert.match(compose, /RABBITMQ_DEFAULT_PASS:.*\$\{RABBITMQ_DEFAULT_PASS/)
  assert.match(compose, /deploy\/connection_env\.py/)
  assert.match(compose, /SQLCHAT_STORAGE_BACKEND: \$\{SQLCHAT_STORAGE_BACKEND:-oss\}/)
  assert.match(compose, /SQLCHAT_STORAGE_ROOT: \$\{SQLCHAT_STORAGE_ROOT:-\/app\/uploads\}/)
  const apiHealthcheck = compose.match(/api:\s*[\s\S]*?healthcheck:\s*([\s\S]*?)\n    restart:/)?.[1]
  assert.ok(apiHealthcheck, 'API must define a health check')
  assert.match(apiHealthcheck, /\/api\/health\/ready/)
  assert.match(apiHealthcheck, /urlopen\([^\n]*timeout=10\)/)
  assert.match(apiHealthcheck, /timeout:\s*30s/)
  assert.match(compose, /rabbitmq-diagnostics/)
  assert.match(compose, /postgres_data:/)
  assert.match(compose, /rabbitmq_data:/)
  assert.match(compose, /uploads_data:/)
  assert.match(compose, /127\.0\.0\.1:\$\{SQLCHAT_HTTP_PORT:-8109\}:80/)
  assert.match(compose, /VITE_API_BASE_URL:\s*\/api/)
  assert.match(compose, /VITE_GITHUB_REPO:/)
  assert.doesNotMatch(compose, /frontend:[\s\S]*?environment:/,
    'the frontend container must not receive backend runtime secrets')
  assert.doesNotMatch(compose, /"(\$\{)?(POSTGRES|RABBITMQ)_(?:PASSWORD|DEFAULT_PASS)=?[^}]*:[0-9]+/)
})

test('worker healthcheck budgets measured cold startup without changing ping failure semantics', () => {
  const compose = read('docker-compose.yml')
  const workerHealthcheck = compose.match(/\n  worker:\n[\s\S]*?\n    healthcheck:\n([\s\S]*?)\n    restart:/)?.[1]
  assert.ok(workerHealthcheck, 'Worker must define a healthcheck')
  assert.match(workerHealthcheck, /test: \["CMD", "python", "-c",/,
    'worker healthcheck must run URL setup and ping in one Python process')
  assert.match(workerHealthcheck, /from deploy\.connection_env import build_connection_urls/)
  assert.match(workerHealthcheck, /build_connection_urls\(os\.environ\)/)
  assert.match(workerHealthcheck, /os\.environ\['SQLCHAT_DATABASE_URL'\] = database_url/)
  assert.match(workerHealthcheck, /os\.environ\['SQLCHAT_BROKER_URL'\] = broker_url/)
  assert.match(workerHealthcheck, /sys\.exit\(0 if celery_app\.control\.ping\(timeout=3\) else 1\)/,
    'a missing ping reply must keep the container unhealthy')

  const timeoutMatch = workerHealthcheck.match(/timeout:\s*(\d+)s/)
  assert.ok(timeoutMatch, 'Worker healthcheck must define its timeout in seconds')
  const timeoutSeconds = Number(timeoutMatch[1])
  // The root observed 9.4078 s end to end: 2.3301 s cold app import and 3.1491 s ping.
  assert.ok(timeoutSeconds * 1000 - 9407.8 >= 2500,
    `timeout must retain at least 2.5 s margin above the 9.4078 s measured probe; got ${timeoutSeconds}s`)
})

test('Compose configuration parses with the example placeholders', (context) => {
  const available = spawnSync('docker', ['compose', 'version'], { encoding: 'utf8' })
  if (available.status !== 0) {
    context.skip('Docker Compose CLI is unavailable; run docker compose config separately')
    return
  }

  const result = spawnSync('docker', [
    'compose', '--project-name', 'sqlchat-s14-test',
    '--env-file', resolve(root, '.env.example'),
    '-f', resolve(root, 'docker-compose.yml'), 'config', '--format', 'json',
  ], { cwd: root, encoding: 'utf8' })
  assert.equal(result.status, 0, result.stderr)

  const config = JSON.parse(result.stdout)
  assert.equal(config.name, 'sqlchat-s14-test')
  assert.deepEqual(Object.keys(config.services).sort(), [
    'api', 'frontend', 'metrics-init', 'migrate', 'postgres', 'rabbitmq', 'worker',
  ])
  assert.equal(config.services.api.expose[0], '8109')
  assert.equal(config.services.api.depends_on.migrate.condition, 'service_completed_successfully')
  assert.equal(config.services.worker.depends_on.migrate.condition, 'service_completed_successfully')
  assert.equal(config.services.api.depends_on['metrics-init'].condition, 'service_completed_successfully')
  assert.equal(config.services.worker.depends_on['metrics-init'].condition, 'service_completed_successfully')
  assert.deepEqual(config.services['metrics-init'].entrypoint, ['python'])
  assert.deepEqual(config.services['metrics-init'].command, ['deploy/init_metrics.py'])
  assert.equal(config.services['metrics-init'].network_mode, 'none')
  assert.equal(config.services['metrics-init'].restart, 'no')
  assert.deepEqual(Object.keys(config.services['metrics-init'].environment), [
    'SQLCHAT_METRICS_MULTIPROCESS_ROOT',
  ])
  assert.equal(config.services['metrics-init'].environment.SQLCHAT_METRICS_MULTIPROCESS_ROOT,
    '/var/lib/sqlchat/prometheus')
  assert.equal(config.services.api.environment.PROMETHEUS_MULTIPROC_DIR,
    '/var/lib/sqlchat/prometheus/api')
  assert.equal(config.services.worker.environment.PROMETHEUS_MULTIPROC_DIR,
    '/var/lib/sqlchat/prometheus/worker')
  assert.equal(config.services.api.environment.SQLCHAT_METRICS_MULTIPROCESS_ROOT,
    '/var/lib/sqlchat/prometheus')
  assert.equal(config.services.worker.environment.SQLCHAT_METRICS_MULTIPROCESS_ROOT,
    '/var/lib/sqlchat/prometheus')
  for (const service of ['api', 'worker', 'metrics-init']) {
    assert.ok(config.services[service].volumes.some((volume) =>
      volume.type === 'volume' && volume.source === 'metrics_multiprocess_data' &&
      volume.target === '/var/lib/sqlchat/prometheus'))
  }
  assert.equal(config.services.postgres.ports, undefined)
  assert.equal(config.services.rabbitmq.ports, undefined)
  assert.equal(config.services.frontend.ports[0].host_ip, '127.0.0.1')
  assert.equal(config.services.frontend.ports[0].published, '8109')
  assert.equal(config.services.frontend.environment, undefined)
  assert.deepEqual(Object.keys(config.services.frontend.build.args).sort(), [
    'VITE_API_BASE_URL', 'VITE_GITHUB_REPO',
  ])
  for (const service of ['api', 'worker', 'migrate']) {
    assert.equal(config.services[service].environment.SQLCHAT_STORAGE_BACKEND, 'oss')
    assert.equal(config.services[service].environment.SQLCHAT_OCR_ENABLED, 'false')
    assert.equal(config.services[service].environment.SQLCHAT_TRIAL_BUILTIN_PORT, '3306')
    assert.equal(config.services[service].environment.SQLCHAT_CONTEXT_AUTO_COMPRESS_ENABLED, 'false')
    assert.equal(config.services[service].environment.SQLCHAT_OBSERVATION_ELISION_ENABLED, 'true')
    assert.equal(config.services[service].environment.SQLCHAT_TOOL_OUTPUT_MAX_ROWS, '50')
    assert.equal(config.services[service].environment.SQLCHAT_TOOL_OUTPUT_PER_TOOL_MAX_CHARACTERS, '')
    assert.equal(config.services[service].environment.SQLCHAT_TOOL_OUTPUT_MAX_LINES, undefined)
  }
})
