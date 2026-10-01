$ErrorActionPreference = 'Stop'
$snapshotRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$repositoryRoot = $snapshotRoot
if (-not (Test-Path (Join-Path $repositoryRoot 'backend/.venv/Scripts/python.exe'))) {
    $repositoryRoot = (Resolve-Path (Join-Path $snapshotRoot '../../..')).Path
}
$pythonPath = Join-Path $repositoryRoot 'backend/.venv/Scripts/python.exe'
$ruffPath = Join-Path $repositoryRoot 'backend/.venv/Scripts/ruff.exe'
$mypyPath = Join-Path $repositoryRoot 'backend/.venv/Scripts/mypy.exe'

function ContainerEnvironment([string] $containerName) {
    $details = docker inspect $containerName | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect isolated test container $containerName" }
    $values = @{}
    foreach ($item in $details[0].Config.Env) {
        $key, $value = $item.Split('=', 2)
        $values[$key] = $value
    }
    return $values
}

$pgValues = ContainerEnvironment 'sqlchat-migration-test-postgres'
$mysqlValues = ContainerEnvironment 'sqlchat-migration-test-mysql'
$env:SQLCHAT_TEST_PG_HOST = '127.0.0.1'
$env:SQLCHAT_TEST_PG_PORT = '15432'
$env:SQLCHAT_TEST_PG_DB = $pgValues['POSTGRES_DB']
$env:SQLCHAT_TEST_PG_USER = $pgValues['POSTGRES_USER']
$env:SQLCHAT_TEST_PG_PASSWORD = $pgValues['POSTGRES_PASSWORD']
$env:SQLCHAT_TEST_MYSQL_HOST = '127.0.0.1'
$env:SQLCHAT_TEST_MYSQL_PORT = '13306'
$env:SQLCHAT_TEST_MYSQL_DB = $mysqlValues['MYSQL_DATABASE']
$env:SQLCHAT_TEST_MYSQL_USER = 'root'
$env:SQLCHAT_TEST_MYSQL_PASSWORD = $mysqlValues['MYSQL_ROOT_PASSWORD']
$mariaValues = ContainerEnvironment 'sqlchat-s12-mariadb'
$env:SQLCHAT_TEST_MARIA_HOST = '127.0.0.1'
$env:SQLCHAT_TEST_MARIA_PORT = '13307'
$env:SQLCHAT_TEST_MARIA_DB = $mariaValues['MARIADB_DATABASE']
$env:SQLCHAT_TEST_MARIA_USER = 'root'
$env:SQLCHAT_TEST_MARIA_PASSWORD = $mariaValues['MARIADB_ROOT_PASSWORD']
$env:SQLCHAT_TEST_DATABASE_URL = 'postgresql+psycopg://' +
    [Uri]::EscapeDataString($env:SQLCHAT_TEST_PG_USER) + ':' +
    [Uri]::EscapeDataString($env:SQLCHAT_TEST_PG_PASSWORD) +
    '@127.0.0.1:15432/' + $env:SQLCHAT_TEST_PG_DB

Push-Location (Join-Path $snapshotRoot 'backend')
try {
    & $ruffPath check app tests 2>&1 | Tee-Object (Join-Path $PSScriptRoot 'ruff.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Ruff failed' }
    & $mypyPath app 2>&1 | Tee-Object (Join-Path $PSScriptRoot 'mypy.txt')
    if ($LASTEXITCODE -ne 0) { throw 'mypy failed' }
    & $pythonPath -m pytest tests/test_pg_read_cursors.py tests/test_adapters_integration.py tests/test_adapters_cancellation.py tests/test_adapters_safety.py tests/test_adapters_contract.py tests/test_mysql_family.py tests/test_mysql_family_outcomes.py tests/test_mysql_family_metadata_errors.py tests/test_mysql_family_workflow.py tests/test_mariadb_integration.py tests/test_sql_repair.py tests/test_sql_error_boundary.py tests/test_sql_termination.py tests/test_workflow_sql_repair.py tests/test_chat_abort.py tests/test_chat_abort_api.py tests/test_chat_abort_real_api.py tests/test_context_cancel.py -q -rs --tb=short 2>&1 | Tee-Object (Join-Path $PSScriptRoot 'pytest.txt')
    if ($LASTEXITCODE -ne 0) { throw 'pytest failed' }
} finally {
    Pop-Location
    foreach ($name in @('SQLCHAT_TEST_PG_PASSWORD', 'SQLCHAT_TEST_MYSQL_PASSWORD', 'SQLCHAT_TEST_DATABASE_URL', 'SQLCHAT_TEST_MARIA_PASSWORD')) {
        Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    }
}
