$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$launcherScript = Join-Path $projectRoot "launcher\pc_monitoring_launcher.py"
$frontendDistIndex = Join-Path $projectRoot "frontend\dist\index.html"
$venvPython = Join-Path $projectRoot "backend\venv\Scripts\python.exe"
$pythonExe = if (Test-Path $venvPython) { $venvPython } else { "python" }

try {
  if (-not (Test-Path $launcherScript)) {
    throw "Файл launcher не найден: $launcherScript"
  }

  if (-not (Test-Path $frontendDistIndex)) {
    Write-Host ""
    Write-Host "Production frontend не найден." -ForegroundColor Red
    Write-Host "Сначала выполните:" -ForegroundColor Yellow
    Write-Host "powershell -ExecutionPolicy Bypass -File .\scripts\build-frontend.ps1" -ForegroundColor DarkGray
    exit 1
  }

  Set-Location $projectRoot

  Write-Host ""
  Write-Host "=== PC Monitoring System: launcher from source ===" -ForegroundColor Cyan
  Write-Host "Используемый Python: $pythonExe" -ForegroundColor DarkGray
  Write-Host "Запуск launcher..." -ForegroundColor Green
  Write-Host ""

  & $pythonExe $launcherScript
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
}
catch {
  Write-Host ""
  Write-Host "Ошибка запуска launcher из исходников: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}

