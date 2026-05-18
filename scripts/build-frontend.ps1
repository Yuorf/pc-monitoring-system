$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendPath = Join-Path $projectRoot "frontend"

try {
  if (-not (Test-Path $frontendPath)) {
    throw "Папка frontend не найдена: $frontendPath"
  }

  Set-Location $frontendPath

  Write-Host ""
  Write-Host "=== PC Monitoring System: production frontend build ===" -ForegroundColor Cyan
  Write-Host "Переход в: $frontendPath" -ForegroundColor DarkGray
  Write-Host "Запуск npm run build..." -ForegroundColor Green
  Write-Host ""

  npm run build
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }

  Write-Host ""
  Write-Host "Production frontend успешно собран." -ForegroundColor Green
  Write-Host "Файлы находятся в frontend/dist" -ForegroundColor Yellow
}
catch {
  Write-Host ""
  Write-Host "Ошибка сборки production frontend: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}

