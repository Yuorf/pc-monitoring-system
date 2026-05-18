$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$backendPath = Join-Path $projectRoot "backend"
$activateScript = Join-Path $backendPath "venv\Scripts\Activate.ps1"

try {
  if (-not (Test-Path $backendPath)) {
    throw "Backend directory not found: $backendPath"
  }

  if (-not (Test-Path $activateScript)) {
    throw "Virtualenv activation script not found: $activateScript"
  }

  Set-Location $backendPath

  Write-Host ""
  Write-Host "=== PC Monitoring System: backend ===" -ForegroundColor Cyan
  Write-Host "Working directory: $backendPath" -ForegroundColor DarkGray
  Write-Host "Activating virtualenv: $activateScript" -ForegroundColor DarkGray

  . $activateScript

  Write-Host "Starting FastAPI at http://127.0.0.1:8000" -ForegroundColor Green
  Write-Host "Use Ctrl+C to stop the server" -ForegroundColor Yellow
  Write-Host ""

  python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
}
catch {
  Write-Host ""
  Write-Host "Backend startup failed: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}
