$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendPath = Join-Path $projectRoot "frontend"

try {
  if (-not (Test-Path $frontendPath)) {
    throw "Frontend directory not found: $frontendPath"
  }

  Set-Location $frontendPath

  Write-Host ""
  Write-Host "=== PC Monitoring System: frontend ===" -ForegroundColor Cyan
  Write-Host "Working directory: $frontendPath" -ForegroundColor DarkGray
  Write-Host "Starting Vite dev server..." -ForegroundColor Green
  Write-Host "Open the UI at http://localhost:5173" -ForegroundColor Yellow
  Write-Host ""

  npm run dev
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
}
catch {
  Write-Host ""
  Write-Host "Frontend startup failed: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}
