$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendDistIndex = Join-Path $projectRoot "frontend\dist\index.html"
$backendPath = Join-Path $projectRoot "backend"
$activateScript = Join-Path $backendPath "venv\Scripts\Activate.ps1"
$productionUrl = "http://127.0.0.1:8000/"

try {
  if (-not (Test-Path $frontendDistIndex)) {
    Write-Host ""
    Write-Host "Production frontend не найден." -ForegroundColor Red
    Write-Host "Сначала соберите frontend:" -ForegroundColor Yellow
    Write-Host "cd frontend" -ForegroundColor DarkGray
    Write-Host "npm run build" -ForegroundColor DarkGray
    exit 1
  }

  if (-not (Test-Path $backendPath)) {
    throw "Папка backend не найдена: $backendPath"
  }

  if (-not (Test-Path $activateScript)) {
    throw "Файл virtualenv не найден: $activateScript"
  }

  Set-Location $backendPath

  Write-Host ""
  Write-Host "=== PC Monitoring System: production ===" -ForegroundColor Cyan
  Write-Host "Переход в: $backendPath" -ForegroundColor DarkGray
  Write-Host "Найден production frontend: $frontendDistIndex" -ForegroundColor Green
  Write-Host "Интерфейс будет доступен на $productionUrl" -ForegroundColor Yellow
  Write-Host ""

  . $activateScript
  $env:DEBUG = "false"

  Start-Process -FilePath "powershell.exe" `
    -WindowStyle Hidden `
    -WorkingDirectory $backendPath `
    -ArgumentList @(
      "-NoProfile",
      "-Command",
      "Start-Sleep -Seconds 2; Start-Process '$productionUrl'"
    )

  Write-Host "Запуск FastAPI production server..." -ForegroundColor Green
  Write-Host "Для остановки используйте Ctrl+C" -ForegroundColor Yellow
  Write-Host ""

  python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
}
catch {
  Write-Host ""
  Write-Host "Ошибка запуска production-режима: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}

