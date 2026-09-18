$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
foreach ($port in @(8000, 3000)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "A porta $port ja esta ocupada. Encerre a instancia anterior antes de iniciar novamente."
    }
}
$pythonExe = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    python -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel criar o ambiente Python.' }
}
& $pythonExe -m pip install -r (Join-Path $projectRoot 'backend/requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Falha na instalacao do backend.' }
Push-Location (Join-Path $projectRoot 'frontend')
try {
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Falha na instalacao do frontend.' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Falha na compilacao do frontend.' }
} finally { Pop-Location }
$logDirectory = Join-Path $projectRoot 'data/logs'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$backendProcess = Start-Process -FilePath $pythonExe -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000') -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDirectory 'backend.out.log') -RedirectStandardError (Join-Path $logDirectory 'backend.err.log')
$nodeExe = (Get-Command node.exe).Source
$frontendProcess = Start-Process -FilePath $nodeExe -ArgumentList @('node_modules/next/dist/bin/next','start','--hostname','127.0.0.1','--port','3000') -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDirectory 'frontend.out.log') -RedirectStandardError (Join-Path $logDirectory 'frontend.err.log')
Write-Host 'BTC Ultra iniciado em http://127.0.0.1:3000'
Write-Host "Processos: API $($backendProcess.Id), painel $($frontendProcess.Id). Logs em $logDirectory"
