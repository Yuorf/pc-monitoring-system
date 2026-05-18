$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$backendScript = Join-Path $PSScriptRoot "start-backend.ps1"
$frontendScript = Join-Path $PSScriptRoot "start-frontend.ps1"

try {
  if (-not (Test-Path $backendScript)) {
    throw "Backend script not found: $backendScript"
  }

  if (-not (Test-Path $frontendScript)) {
    throw "Frontend script not found: $frontendScript"
  }

  Write-Host ""
  Write-Host "=== PC Monitoring System: dev launch ===" -ForegroundColor Cyan
  Write-Host "Opening two PowerShell windows:" -ForegroundColor Green
  Write-Host "  1. Backend API: http://127.0.0.1:8000" -ForegroundColor DarkGray
  Write-Host "  2. Frontend UI: http://localhost:5173" -ForegroundColor DarkGray
  Write-Host ""

  Start-Process -FilePath "powershell.exe" `
    -WorkingDirectory $projectRoot `
    -ArgumentList @(
      "-NoExit",
      "-ExecutionPolicy", "Bypass",
      "-File", $backendScript
    )

  Start-Process -FilePath "powershell.exe" `
    -WorkingDirectory $projectRoot `
    -ArgumentList @(
      "-NoExit",
      "-ExecutionPolicy", "Bypass",
      "-File", $frontendScript
    )

  Write-Host "After both windows start, open: http://localhost:5173/" -ForegroundColor Yellow
  Write-Host "If one window fails, it will stay open for troubleshooting." -ForegroundColor Yellow
}
catch {
  Write-Host ""
  Write-Host "Dev startup failed: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}
