import os
import subprocess
import time
from pathlib import Path

from app.core.config import settings


LHM_PROCESS_NAME = "LibreHardwareMonitor.exe"
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _normalize_configured_path(path_value: str | None) -> Path | None:
    if path_value is None:
        return None

    normalized = path_value.strip()
    if not normalized:
        return None

    configured_path = Path(normalized)
    if configured_path.is_absolute():
        return configured_path
    return BACKEND_DIR / configured_path


def _deduplicate_paths(paths: list[Path]) -> list[Path]:
    unique_paths: list[Path] = []
    seen: set[str] = set()

    for path in paths:
        normalized = str(path.resolve(strict=False)).lower() if os.name == "nt" else str(
            path.resolve(strict=False)
        )
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_paths.append(path)

    return unique_paths


def _error_text(error: Exception) -> str:
    error_text = str(error).strip()
    return error_text or error.__class__.__name__


def get_lhm_candidate_paths() -> list[Path]:
    candidates: list[Path] = []

    configured_path = _normalize_configured_path(settings.LIBRE_HARDWARE_MONITOR_EXE_PATH)
    if configured_path is not None:
        candidates.append(configured_path)

    candidates.extend(
        [
            BACKEND_DIR / "tools" / "LibreHardwareMonitor" / LHM_PROCESS_NAME,
            PROJECT_ROOT / "tools" / "LibreHardwareMonitor" / LHM_PROCESS_NAME,
            (BACKEND_DIR / ".." / "tools" / "LibreHardwareMonitor" / LHM_PROCESS_NAME),
        ]
    )

    return _deduplicate_paths(candidates)


def find_lhm_executable() -> Path | None:
    for candidate_path in get_lhm_candidate_paths():
        if candidate_path.is_file():
            return candidate_path
    return None


def is_process_running(process_name: str) -> bool:
    try:
        if os.name == "nt":
            result = subprocess.run(
                [
                    "tasklist",
                    "/FI",
                    f"IMAGENAME eq {process_name}",
                    "/FO",
                    "CSV",
                    "/NH",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            output = result.stdout.strip().lower()
            return bool(output) and process_name.lower() in output and "no tasks are running" not in output

        result = subprocess.run(
            ["ps", "-A", "-o", "comm="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        target_name = process_name.lower()
        return any(
            Path(line.strip()).name.lower() == target_name
            for line in result.stdout.splitlines()
            if line.strip()
        )
    except Exception:
        return False


def start_lhm_if_needed() -> dict[str, object]:
    process_name = LHM_PROCESS_NAME

    if not settings.LIBRE_HARDWARE_MONITOR_ENABLED:
        return {
            "status": "disabled",
            "process_name": process_name,
        }

    if not settings.LIBRE_HARDWARE_MONITOR_AUTO_START:
        return {
            "status": "skipped",
            "process_name": process_name,
        }

    if is_process_running(process_name):
        return {
            "status": "already_running",
            "process_name": process_name,
        }

    candidate_paths = get_lhm_candidate_paths()
    executable_path = find_lhm_executable()
    if executable_path is None:
        return {
            "status": "not_found",
            "process_name": process_name,
            "checked_paths": [str(path) for path in candidate_paths],
        }

    try:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        subprocess.Popen(
            [str(executable_path)],
            cwd=str(executable_path.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        time.sleep(max(settings.LIBRE_HARDWARE_MONITOR_STARTUP_WAIT_SECONDS, 0.0))
        return {
            "status": "started",
            "process_name": process_name,
            "exe_path": str(executable_path),
        }
    except Exception as error:
        return {
            "status": "error",
            "process_name": process_name,
            "exe_path": str(executable_path),
            "error": _error_text(error),
        }
