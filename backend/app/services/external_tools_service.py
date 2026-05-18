import os
import shutil
import subprocess
import time
from pathlib import Path

from app.core.config import settings


LHM_PROCESS_NAME = "LibreHardwareMonitor.exe"
SMARTCTL_EXE_NAME = "smartctl.exe"
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SMARTCTL_PROGRAM_FILES_CANDIDATES = (
    Path(r"C:\Program Files\smartmontools\bin") / SMARTCTL_EXE_NAME,
    Path(r"C:\Program Files (x86)\smartmontools\bin") / SMARTCTL_EXE_NAME,
)


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


def get_smartctl_candidate_paths() -> list[Path]:
    candidates = [
        BACKEND_DIR / "tools" / "smartmontools" / "bin" / SMARTCTL_EXE_NAME,
        BACKEND_DIR / "tools" / "smartmontools" / SMARTCTL_EXE_NAME,
        PROJECT_ROOT / "tools" / "smartmontools" / "bin" / SMARTCTL_EXE_NAME,
        PROJECT_ROOT / "tools" / "smartmontools" / SMARTCTL_EXE_NAME,
    ]

    for executable_name in ("smartctl", SMARTCTL_EXE_NAME):
        executable_path = shutil.which(executable_name)
        if executable_path:
            candidates.append(Path(executable_path))

    candidates.extend(SMARTCTL_PROGRAM_FILES_CANDIDATES)
    return _deduplicate_paths(candidates)


def find_smartctl_executable() -> Path | None:
    for candidate_path in get_smartctl_candidate_paths():
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
                **get_hidden_subprocess_kwargs(),
            )
            output = result.stdout.strip().lower()
            return bool(output) and process_name.lower() in output and "no tasks are running" not in output

        result = subprocess.run(
            ["ps", "-A", "-o", "comm="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            **get_hidden_subprocess_kwargs(),
        )
        target_name = process_name.lower()
        return any(
            Path(line.strip()).name.lower() == target_name
            for line in result.stdout.splitlines()
            if line.strip()
        )
    except Exception:
        return False


def _build_windows_startupinfo() -> subprocess.STARTUPINFO | None:
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return None

    startup_info = subprocess.STARTUPINFO()
    startup_info.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    startup_info.wShowWindow = getattr(
        subprocess,
        "SW_HIDE",
        getattr(subprocess, "SW_MINIMIZE", 6),
    )
    return startup_info


def get_hidden_subprocess_kwargs() -> dict[str, object]:
    if os.name != "nt":
        return {}

    kwargs: dict[str, object] = {}
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if creation_flags:
        kwargs["creationflags"] = creation_flags

    startup_info = _build_windows_startupinfo()
    if startup_info is not None:
        kwargs["startupinfo"] = startup_info

    return kwargs


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
        subprocess.Popen(
            [str(executable_path)],
            cwd=str(executable_path.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **get_hidden_subprocess_kwargs(),
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


def check_external_tools_health() -> dict[str, object]:
    lhm_executable = find_lhm_executable()
    lhm_payload: dict[str, object] = {
        "process_name": LHM_PROCESS_NAME,
    }
    if not settings.LIBRE_HARDWARE_MONITOR_ENABLED:
        lhm_payload["status"] = "disabled"
    elif is_process_running(LHM_PROCESS_NAME):
        lhm_payload["status"] = "already_running"
    elif lhm_executable is not None:
        lhm_payload["status"] = "available"
    else:
        lhm_payload["status"] = "not_found"
        lhm_payload["checked_paths"] = [
            str(path) for path in get_lhm_candidate_paths()
        ]

    if lhm_executable is not None:
        lhm_payload["exe_path"] = str(lhm_executable)

    try:
        smartctl_executable = find_smartctl_executable()
        if smartctl_executable is not None:
            smartctl_payload: dict[str, object] = {
                "status": "ok",
                "exe_path": str(smartctl_executable),
            }
        else:
            smartctl_payload = {
                "status": "not_found",
                "checked_paths": [
                    str(path) for path in get_smartctl_candidate_paths()
                ],
            }
    except Exception as error:
        smartctl_payload = {
            "status": "error",
            "error": _error_text(error),
        }

    return {
        "libre_hardware_monitor": lhm_payload,
        "smartctl": smartctl_payload,
    }
