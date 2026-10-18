# Stops backend and frontend started by scripts/dev-start.ps1 (plus anything else on their ports),
# then the Docker services. -KeepDocker leaves Postgres/Redis running; data volumes are never removed.
param(
    [switch]$KeepDocker,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

$root = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $root '.run'

function Stop-Tree([int]$ProcessId, [string]$Name) {
    if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
        # /T is needed: uvicorn --reload and npm each spawn child processes
        taskkill.exe /PID $ProcessId /T /F | Out-Null
        Write-Host "    $Name (PID $ProcessId) beendet"
    }
}

function Stop-DevServer([string]$Name, [int]$Port) {
    Write-Host "==> $Name" -ForegroundColor Cyan
    $pidFile = Join-Path $runDir "$($Name.ToLower()).pid"
    if (Test-Path $pidFile) {
        Stop-Tree ([int](Get-Content $pidFile)) $Name
        Remove-Item $pidFile -Force
    }
    # catches servers started outside this script, e.g. by hand in a terminal
    $owners = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($o in $owners) { Stop-Tree $o "$Name auf Port $Port" }
    if (-not (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)) {
        Write-Host "    Port $Port frei"
    } else {
        Write-Warning "Port $Port ist noch belegt"
    }
}

Stop-DevServer 'Backend' $BackendPort
Stop-DevServer 'Frontend' $FrontendPort

if (-not $KeepDocker) {
    Write-Host '==> Docker: Postgres + Redis' -ForegroundColor Cyan
    docker compose -f (Join-Path $root 'deploy/docker-compose.dev.yml') stop
}
