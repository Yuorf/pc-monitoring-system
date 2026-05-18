$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$portableExe = Join-Path $projectRoot "dist\PCMonitoringSystem\PCMonitoringSystem.exe"
$installerScript = Join-Path $projectRoot "installer\PCMonitoringSystem.iss"
$installerOutputDir = Join-Path $projectRoot "dist\installer"
$installerOutputExe = Join-Path $installerOutputDir "PCMonitoringSystemSetup-0.1.0.exe"

function Get-InnoSetupCompilerPath {
  $envPath = $env:INNO_SETUP_COMPILER
  if ($envPath -and (Test-Path $envPath)) {
    return $envPath
  }

  $command = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
  if ($command -and $command.Source) {
    return $command.Source
  }

  foreach ($candidate in @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
  )) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }

  return $null
}

try {
  if (-not (Test-Path $portableExe)) {
    Write-Host ""
    Write-Host "Portable launcher не найден." -ForegroundColor Red
    Write-Host "Сначала выполните:" -ForegroundColor Yellow
    Write-Host "powershell -ExecutionPolicy Bypass -File .\scripts\build-launcher.ps1" -ForegroundColor DarkGray
    exit 1
  }

  if (-not (Test-Path $installerScript)) {
    throw "Файл installer script не найден: $installerScript"
  }

  $isccPath = Get-InnoSetupCompilerPath
  if (-not $isccPath) {
    Write-Host ""
    Write-Host "Inno Setup Compiler (ISCC.exe) не найден." -ForegroundColor Red
    Write-Host "Installer script уже подготовлен:" -ForegroundColor Yellow
    Write-Host $installerScript -ForegroundColor DarkGray
    Write-Host "Установите Inno Setup или укажите путь через INNO_SETUP_COMPILER." -ForegroundColor Yellow
    Write-Host "Например: C:\Program Files (x86)\Inno Setup 6\ISCC.exe" -ForegroundColor DarkGray
    exit 1
  }

  New-Item -ItemType Directory -Path $installerOutputDir -Force | Out-Null
  Set-Location $projectRoot

  Write-Host ""
  Write-Host "=== PC Monitoring System: build installer ===" -ForegroundColor Cyan
  Write-Host "Используемый Inno Setup Compiler: $isccPath" -ForegroundColor DarkGray
  Write-Host "Сборка installer..." -ForegroundColor Green
  Write-Host ""

  & $isccPath $installerScript
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }

  Write-Host ""
  Write-Host "Installer успешно собран." -ForegroundColor Green
  Write-Host "Результат: $installerOutputExe" -ForegroundColor Yellow
}
catch {
  Write-Host ""
  Write-Host "Ошибка сборки installer: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}
