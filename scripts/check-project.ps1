$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$backendPath = Join-Path $projectRoot "backend"
$frontendPath = Join-Path $projectRoot "frontend"
$activateScript = Join-Path $backendPath "venv\Scripts\Activate.ps1"
$pythonFiles = @(
  "app/main.py",
  "app/services/ml_prediction_service.py",
  "app/services/system_info.py",
  "app/services/external_tools_service.py"
)

try {
  if (-not (Test-Path $backendPath)) {
    throw "Backend directory not found: $backendPath"
  }

  if (-not (Test-Path $frontendPath)) {
    throw "Frontend directory not found: $frontendPath"
  }

  if (-not (Test-Path $activateScript)) {
    throw "Virtualenv activation script not found: $activateScript"
  }

  Write-Host ""
  Write-Host "=== Backend checks ===" -ForegroundColor Cyan
  Set-Location $backendPath
  . $activateScript

  foreach ($file in $pythonFiles) {
    if (-not (Test-Path $file)) {
      throw "py_compile target not found: $file"
    }

    Write-Host "py_compile -> $file" -ForegroundColor Green
    python -m py_compile $file
    if ($LASTEXITCODE -ne 0) {
      throw "py_compile failed for: $file"
    }
  }

  Write-Host ""
  Write-Host "=== Frontend checks ===" -ForegroundColor Cyan
  Set-Location $frontendPath

  Write-Host "npm run lint" -ForegroundColor Green
  npm run lint
  if ($LASTEXITCODE -ne 0) {
    throw "npm run lint failed with exit code $LASTEXITCODE"
  }

  Write-Host ""
  Write-Host "npm run build" -ForegroundColor Green
  npm run build
  if ($LASTEXITCODE -ne 0) {
    throw "npm run build failed with exit code $LASTEXITCODE"
  }

  Write-Host ""
  Write-Host "Project checks completed successfully." -ForegroundColor Green
}
catch {
  Write-Host ""
  Write-Host "Project checks failed: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}
