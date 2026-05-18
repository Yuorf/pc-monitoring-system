$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$launcherScript = Join-Path $projectRoot "launcher\pc_monitoring_launcher.py"
$launcherRequirements = Join-Path $projectRoot "launcher\requirements.txt"
$frontendDistIndex = Join-Path $projectRoot "frontend\dist\index.html"
$venvPython = Join-Path $projectRoot "backend\venv\Scripts\python.exe"
$pythonExe = if (Test-Path $venvPython) { $venvPython } else { "python" }
$distRoot = Join-Path $projectRoot "dist"
$launcherName = "PCMonitoringSystem"
$launcherDistDir = Join-Path $distRoot $launcherName
$buildRoot = Join-Path $projectRoot "build\pyinstaller"
$workPath = Join-Path $buildRoot "work"
$specPath = $buildRoot
$stagingRoot = Join-Path $buildRoot "staging"
$stagingBackend = Join-Path $stagingRoot "backend"
$stagingFrontendDist = Join-Path $stagingRoot "frontend\dist"

function Copy-DirectoryFiltered {
  param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Destination,
    [string[]]$ExcludedRelativeDirectories = @(),
    [string[]]$ExcludedFilePatterns = @(),
    [string]$RootPath = $Source
  )

  New-Item -ItemType Directory -Path $Destination -Force | Out-Null

  $excludeDirs = @("__pycache__", ".git", "venv", "node_modules", "src")
  $excludeFiles = @("*.pyc", "*.pyo", "*.db", "*.tmp", "*.temp", "*.log")
  $resolvedRootPath = [System.IO.Path]::GetFullPath($RootPath)
  $normalizedExcludedDirectories = $ExcludedRelativeDirectories | ForEach-Object {
    $_.Replace("/", "\").TrimStart("\")
  }

  foreach ($item in Get-ChildItem -Path $Source -Force) {
    $itemFullPath = [System.IO.Path]::GetFullPath($item.FullName)
    $relativePath = $itemFullPath.Substring($resolvedRootPath.Length).TrimStart("\")
    $normalizedRelativePath = $relativePath.Replace("/", "\")

    if ($item.PSIsContainer) {
      if ($excludeDirs -contains $item.Name) {
        continue
      }

      if ($normalizedExcludedDirectories -contains $normalizedRelativePath) {
        continue
      }

      Copy-DirectoryFiltered `
        -Source $item.FullName `
        -Destination (Join-Path $Destination $item.Name) `
        -ExcludedRelativeDirectories $ExcludedRelativeDirectories `
        -ExcludedFilePatterns $ExcludedFilePatterns `
        -RootPath $resolvedRootPath
      continue
    }

    $skipFile = $false
    foreach ($pattern in @($excludeFiles + $ExcludedFilePatterns)) {
      if ($item.Name -like $pattern) {
        $skipFile = $true
        break
      }
    }

    if ($skipFile) {
      continue
    }

    Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $Destination $item.Name) -Force
  }
}

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

  $previousNativeErrorPreference = $null
  if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -Scope Global -ErrorAction SilentlyContinue) {
    $previousNativeErrorPreference = $global:PSNativeCommandUseErrorActionPreference
  }
  $global:PSNativeCommandUseErrorActionPreference = $false

  & $pythonExe -c "import PyInstaller"
  if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "PyInstaller не установлен." -ForegroundColor Red
    Write-Host "Установите его командой:" -ForegroundColor Yellow
    Write-Host "python -m pip install pyinstaller" -ForegroundColor DarkGray
    exit 1
  }

  & $pythonExe -c "import webview"
  if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "pywebview не установлен." -ForegroundColor Red
    Write-Host "Установите его командой:" -ForegroundColor Yellow
    Write-Host "python -m pip install pywebview" -ForegroundColor DarkGray
    if (Test-Path $launcherRequirements) {
      Write-Host "Или:" -ForegroundColor Yellow
      Write-Host "python -m pip install -r launcher\\requirements.txt" -ForegroundColor DarkGray
    }
    exit 1
  }

  $resolvedProjectRoot = Resolve-Path $projectRoot
  $resolvedDistRoot = Join-Path $resolvedProjectRoot "dist"
  $resolvedLauncherDistDir = Join-Path $resolvedDistRoot $launcherName
  $resolvedBuildRoot = Join-Path $resolvedProjectRoot "build\pyinstaller"
  $resolvedStagingRoot = Join-Path $resolvedBuildRoot "staging"

  foreach ($pathToRemove in @($resolvedLauncherDistDir, $resolvedBuildRoot)) {
    if (Test-Path $pathToRemove) {
      Remove-Item -LiteralPath $pathToRemove -Recurse -Force
    }
  }

  New-Item -ItemType Directory -Path $stagingBackend -Force | Out-Null
  New-Item -ItemType Directory -Path $stagingFrontendDist -Force | Out-Null
  New-Item -ItemType Directory -Path (Join-Path $stagingBackend "data") -Force | Out-Null

  Copy-DirectoryFiltered -Source (Join-Path $projectRoot "backend\app") -Destination (Join-Path $stagingBackend "app")
  Copy-DirectoryFiltered `
    -Source (Join-Path $projectRoot "backend\ml") `
    -Destination (Join-Path $stagingBackend "ml") `
    -ExcludedRelativeDirectories @(
      "data\raw",
      "data\processed",
      "reports",
      "reports_local_backup",
      "models_local_backup"
    ) `
    -ExcludedFilePatterns @("*.csv", "*.parquet", "*.jsonl")
  Copy-DirectoryFiltered -Source (Join-Path $projectRoot "frontend\dist") -Destination $stagingFrontendDist

  if (Test-Path (Join-Path $projectRoot "backend\tools")) {
    Copy-DirectoryFiltered -Source (Join-Path $projectRoot "backend\tools") -Destination (Join-Path $stagingBackend "tools")
  }

  foreach ($fileName in @(".env", ".env.example", "requirements.txt")) {
    $sourceFile = Join-Path $projectRoot "backend\$fileName"
    if (Test-Path $sourceFile) {
      Copy-Item -LiteralPath $sourceFile -Destination (Join-Path $stagingBackend $fileName) -Force
    }
  }

  Write-Host ""
  Write-Host "=== PC Monitoring System: build launcher ===" -ForegroundColor Cyan
  Write-Host "Используемый Python: $pythonExe" -ForegroundColor DarkGray
  Write-Host "Сборка launcher через PyInstaller..." -ForegroundColor Green
  Write-Host ""

  $pyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onedir",
    "--name", $launcherName,
    "--distpath", $distRoot,
    "--workpath", $workPath,
    "--specpath", $specPath,
    "--collect-all", "fastapi",
    "--collect-all", "starlette",
    "--collect-all", "uvicorn",
    "--collect-all", "sqlalchemy",
    "--collect-all", "pydantic",
    "--collect-all", "pydantic_settings",
    "--collect-all", "joblib",
    "--collect-all", "numpy",
    "--collect-all", "pandas",
    "--collect-all", "psutil",
    "--collect-all", "psycopg2",
    "--collect-all", "dotenv",
    "--collect-all", "sklearn",
    "--collect-all", "scipy",
    "--collect-all", "httptools",
    "--collect-all", "websockets",
    "--collect-all", "webview",
    "--collect-all", "pythonnet",
    "--collect-all", "clr_loader",
    "--collect-all", "bottle",
    "--collect-all", "proxy_tools",
    "--hidden-import", "webview.platforms.edgechromium",
    "--hidden-import", "webview.platforms.winforms",
    "--hidden-import", "webview.platforms.mshtml",
    "--add-data", "$stagingBackend;backend",
    "--add-data", "$stagingFrontendDist;frontend/dist",
    $launcherScript
  )

  & $pythonExe @pyInstallerArgs
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }

  if ($null -ne $previousNativeErrorPreference) {
    $global:PSNativeCommandUseErrorActionPreference = $previousNativeErrorPreference
  }

  Write-Host ""
  Write-Host "Launcher успешно собран." -ForegroundColor Green
  Write-Host "Результат: dist\PCMonitoringSystem\PCMonitoringSystem.exe" -ForegroundColor Yellow
}
catch {
  if (Get-Variable -Name previousNativeErrorPreference -Scope Local -ErrorAction SilentlyContinue) {
    if ($null -ne $previousNativeErrorPreference) {
      $global:PSNativeCommandUseErrorActionPreference = $previousNativeErrorPreference
    }
  }
  Write-Host ""
  Write-Host "Ошибка сборки launcher: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}


