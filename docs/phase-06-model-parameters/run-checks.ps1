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
    & $pythonPath -m pytest -q -rs --tb=short tests/test_model_parameters.py tests/test_model_protocol.py tests/test_chat_graph.py tests/test_chat_api.py tests/test_chat_abort.py tests/test_chat_abort_api.py tests/test_chat_abort_real_api.py tests/test_context_compress.py tests/test_context_cancel.py tests/test_runtime_governance.py tests/test_output_guard_contract.py tests/test_sql_repair.py tests/test_sql_error_boundary.py tests/test_sql_termination.py tests/test_workflow_graph.py tests/test_workflow_integration.py tests/test_workflow_identifiers.py tests/test_workflow_large_import.py tests/test_workflow_sql_repair.py tests/test_workflow_text.py tests/test_workflow_evidence.py tests/test_workflow_corrections.py 2>&1 | Tee-Object (Join-Path $PSScriptRoot 'pytest.txt')
    if ($LASTEXITCODE -ne 0) { throw 'pytest failed' }
} finally {
    Pop-Location
    foreach ($name in @('SQLCHAT_TEST_PG_PASSWORD', 'SQLCHAT_TEST_MYSQL_PASSWORD', 'SQLCHAT_TEST_DATABASE_URL')) {
        Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    }
}
