# PC Monitoring System

## Структура проекта

- `backend` — FastAPI backend
- `frontend` — Vite/React frontend
- `scripts` — PowerShell-скрипты для локального запуска и проверки

## Локальный запуск

### Backend

Из папки проекта:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-backend.ps1
```

Что делает скрипт:

- переходит в `backend`
- активирует `backend\venv`
- запускает FastAPI через `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`

Backend слушает:

- `http://127.0.0.1:8000`

### Frontend

Из папки проекта:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-frontend.ps1
```

Что делает скрипт:

- переходит в `frontend`
- запускает `npm run dev`

Frontend доступен по адресу:

- `http://localhost:5173`

### Backend + frontend вместе

Из папки проекта:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-dev.ps1
```

Скрипт открывает два отдельных окна PowerShell:

- одно для backend
- одно для frontend

После запуска интерфейс нужно открывать здесь:

- `http://localhost:5173/`

## Production-запуск

### Сборка frontend

Из папки проекта:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-frontend.ps1
```

Скрипт собирает production frontend в `frontend/dist`.

### Запуск production

После сборки frontend:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-production.ps1
```

Что делает скрипт:

- проверяет наличие `frontend/dist/index.html`
- активирует `backend\venv`
- запускает FastAPI на `127.0.0.1:8000`
- открывает production-интерфейс в браузере

Production-интерфейс доступен по адресу:

- `http://127.0.0.1:8000/`

Для production-запуска `npm run dev` и Vite frontend server не нужны.

`start-dev.ps1` остаётся сценарием только для разработки.

## Launcher / exe

Сначала соберите production frontend:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-frontend.ps1
```

Проверка launcher из исходников:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-launcher-source.ps1
```

Для встроенного окна launcher нужен `pywebview`:

```powershell
python -m pip install pywebview
```

Сборка portable launcher через PyInstaller:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-launcher.ps1
```

Готовый exe будет лежать здесь:

- `dist\PCMonitoringSystem\PCMonitoringSystem.exe`

Запуск portable launcher:

```powershell
.\dist\PCMonitoringSystem\PCMonitoringSystem.exe
```

Для portable SMART желательно положить `smartctl.exe` в
`backend/tools/smartmontools/bin`.

Если bundled `smartctl` отсутствует, backend попробует использовать системный
`smartctl`, если он установлен.

Сборка installer:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-installer.ps1
```

Если Inno Setup установлен, installer появится здесь:

- `dist\installer\PCMonitoringSystemSetup-0.1.0.exe`

Если Inno Setup не установлен, скрипт подскажет путь к `.iss` файлу и что
нужно установить `ISCC.exe`.

`start-dev.ps1` остаётся сценарием только для разработки. Для production и
portable-запуска Vite не нужен.

Для полного набора датчиков приложение желательно запускать от имени
администратора.

Portable launcher и installer не являются заменой dev-режиму, а работают
поверх production backend + frontend build.

## Проверка проекта

Полная локальная проверка:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check-project.ps1
```

Скрипт выполняет:

- `python -m py_compile` для:
  - `app/main.py`
  - `app/services/ml_prediction_service.py`
  - `app/services/system_info.py`
  - `app/services/external_tools_service.py`
- `npm run lint`
- `npm run build`

## Порты

- backend: `127.0.0.1:8000`
- frontend: `localhost:5173`

## База данных

- По умолчанию backend использует SQLite.
- Текущие скрипты запуска не меняют настройку SQLite/PostgreSQL.

## Датчики и права доступа

- Для полного набора аппаратных датчиков backend лучше запускать от имени администратора.
- Это особенно полезно для корректной работы проверок, связанных с Libre Hardware Monitor и SMART.

## Примечания

- Vite proxy проксирует `/api/*` на backend.
- Для проверки backend через frontend proxy откройте интерфейс на `http://localhost:5173/`.
- Если нужно обойти Vite proxy и обращаться к backend напрямую, используйте `VITE_API_PROXY_BYPASS=true`.
