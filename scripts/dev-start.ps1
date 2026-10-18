# Starts Postgres/Redis (Docker), runs migrations, then backend (uvicorn) and frontend (vite)
# in the background. Logs and PIDs go to .run/. Stop everything with scripts/dev-stop.ps1.
param(
    [switch]$SkipMigrate,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $root '.run'
New-Item -ItemType Directory -Force $runDir | Out-Null

function Test-PortListening([int]$Port) {
    $null -ne (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Wait-Port([int]$Port, [int]$TimeoutSec, [string]$Name, [string]$Log) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortListening $Port) { return }
        Start-Sleep -Milliseconds 500
    }
    Write-Warning "$Name lauscht nach $TimeoutSec s noch nicht auf Port $Port - siehe $Log"
}

Write-Host '==> Docker: Postgres + Redis' -ForegroundColor Cyan
docker compose -f (Join-Path $root 'deploy/docker-compose.dev.yml') up -d --wait
if ($LASTEXITCODE -ne 0) { throw 'docker compose up fehlgeschlagen (laeuft Docker Desktop?)' }

$python = Join-Path $root '.venv/Scripts/python.exe'
if (-not $SkipMigrate) {
    Write-Host '==> Alembic: upgrade head' -ForegroundColor Cyan
    Push-Location $root
    try { & $python -m alembic upgrade head } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw 'alembic upgrade head fehlgeschlagen' }
}

Write-Host "==> Backend (Port $BackendPort)" -ForegroundColor Cyan
$backendLog = Join-Path $runDir 'backend.log'
if (Test-PortListening $BackendPort) {
    Write-Host "    Port $BackendPort ist schon belegt - uebersprungen"
} else {
    # cmd.exe redirects so the servers don't inherit (and hold open) the caller's stdout pipe
    $cmd = "`"$python`" -m uvicorn kairos.api:app --reload --host 0.0.0.0 --port $BackendPort > `"$backendLog`" 2>&1"
    $p = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', "`"$cmd`"" -WorkingDirectory $root -WindowStyle Hidden -PassThru
    Set-Content -Path (Join-Path $runDir 'backend.pid') -Value $p.Id -Encoding ascii
    Wait-Port $BackendPort 30 'Backend' $backendLog
}

Write-Host "==> Frontend (Port $FrontendPort)" -ForegroundColor Cyan
$frontendLog = Join-Path $runDir 'frontend.log'
if (Test-PortListening $FrontendPort) {
    Write-Host "    Port $FrontendPort ist schon belegt - uebersprungen"
} else {
    $env:KAIROS_API_PROXY_TARGET = "http://localhost:$BackendPort"
    $cmd = "npm.cmd run dev -- --port $FrontendPort --strictPort > `"$frontendLog`" 2>&1"
    $p = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', "`"$cmd`"" -WorkingDirectory (Join-Path $root 'web') -WindowStyle Hidden -PassThru
    Set-Content -Path (Join-Path $runDir 'frontend.pid') -Value $p.Id -Encoding ascii
    Wait-Port $FrontendPort 60 'Frontend' $frontendLog
}

Write-Host ''
Write-Host "Backend:  http://localhost:$BackendPort" -ForegroundColor Green
Write-Host "Frontend: http://localhost:$FrontendPort" -ForegroundColor Green
Write-Host "Logs:     $runDir"
Write-Host 'Beenden:  .\scripts\dev-stop.ps1'
