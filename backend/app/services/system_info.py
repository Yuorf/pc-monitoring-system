import platform
import subprocess
import sys

import psutil


def _round_gb(bytes_value: int | float | None) -> float | None:
    if bytes_value is None:
        return None
    return round(bytes_value / (1024**3), 2)


def _to_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _collect_cpu_info() -> dict[str, object]:
    physical_cores = None
    logical_cores = None
    current_frequency_mhz = None
    min_frequency_mhz = None
    max_frequency_mhz = None
    cpu_usage = None
    per_core_usage = None

    try:
        physical_cores = psutil.cpu_count(logical=False)
    except Exception:
        physical_cores = None

    try:
        logical_cores = psutil.cpu_count(logical=True)
    except Exception:
        logical_cores = None

    try:
        cpu_freq = psutil.cpu_freq()
        if cpu_freq is not None:
            current_frequency_mhz = _to_float(round(cpu_freq.current, 2))
            min_frequency_mhz = _to_float(round(cpu_freq.min, 2))
            max_frequency_mhz = _to_float(round(cpu_freq.max, 2))
    except Exception:
        current_frequency_mhz = None
        min_frequency_mhz = None
        max_frequency_mhz = None

    try:
        per_core_usage = psutil.cpu_percent(interval=1, percpu=True)
        if per_core_usage:
            cpu_usage = round(sum(per_core_usage) / len(per_core_usage), 2)
        else:
            cpu_usage = 0.0
    except Exception:
        cpu_usage = None
        per_core_usage = None

    return {
        "physical_cores": physical_cores,
        "logical_cores": logical_cores,
        "current_frequency_mhz": current_frequency_mhz,
        "min_frequency_mhz": min_frequency_mhz,
        "max_frequency_mhz": max_frequency_mhz,
        "cpu_usage": cpu_usage,
        "per_core_usage": per_core_usage,
    }


def _collect_ram_info() -> dict[str, float | None]:
    total_gb = None
    used_gb = None
    available_gb = None
    percent = None

    try:
        memory = psutil.virtual_memory()
        total_gb = _round_gb(memory.total)
        used_gb = _round_gb(memory.used)
        available_gb = _round_gb(memory.available)
        percent = _to_float(memory.percent)
    except Exception:
        total_gb = None
        used_gb = None
        available_gb = None
        percent = None

    return {
        "total_gb": total_gb,
        "used_gb": used_gb,
        "available_gb": available_gb,
        "percent": percent,
    }


def _collect_disks_info() -> list[dict[str, object]]:
    disks = []

    try:
        partitions = psutil.disk_partitions()
    except Exception:
        return disks

    for partition in partitions:
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            disks.append(
                {
                    "device": partition.device,
                    "mountpoint": partition.mountpoint,
                    "filesystem": partition.fstype,
                    "total_gb": _round_gb(usage.total),
                    "used_gb": _round_gb(usage.used),
                    "free_gb": _round_gb(usage.free),
                    "percent": _to_float(usage.percent),
                }
            )
        except Exception:
            continue

    return disks


def _collect_gpu_info() -> dict[str, object]:
    gpu_info = {
        "name": None,
        "usage_percent": None,
        "memory_used_mb": None,
        "memory_total_mb": None,
        "temperature_celsius": None,
    }

    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        first_line = next(
            (line.strip() for line in result.stdout.splitlines() if line.strip()),
            "",
        )
        if first_line:
            parts = [part.strip() for part in first_line.split(",")]
            gpu_info["name"] = parts[0] if len(parts) > 0 and parts[0] else None
            gpu_info["usage_percent"] = _to_float(parts[1] if len(parts) > 1 else None)
            gpu_info["memory_used_mb"] = _to_int(parts[2] if len(parts) > 2 else None)
            gpu_info["memory_total_mb"] = _to_int(parts[3] if len(parts) > 3 else None)
            gpu_info["temperature_celsius"] = _to_float(
                parts[4] if len(parts) > 4 else None
            )
            return gpu_info
    except Exception:
        pass

    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_VideoController | Select-Object -First 1 Name,AdapterRAM | ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        output = result.stdout.strip()
        if output:
            import json

            gpu_data = json.loads(output)
            gpu_info["name"] = gpu_data.get("Name")
            gpu_info["memory_total_mb"] = _to_int(
                round(gpu_data.get("AdapterRAM", 0) / (1024**2), 2)
                if gpu_data.get("AdapterRAM") is not None
                else None
            )
    except Exception:
        pass

    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "$samples = (Get-Counter '\\GPU Engine(*)\\Utilization Percentage')."
                    "CounterSamples; "
                    "$sum = ($samples | Measure-Object -Property CookedValue -Sum).Sum; "
                    "if ($null -eq $sum) { '' } "
                    "else { [math]::Min(100, [math]::Round($sum, 2)) }"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        gpu_info["usage_percent"] = _to_float(result.stdout.strip())
    except Exception:
        pass

    return gpu_info


def _collect_battery_info() -> dict[str, object] | None:
    try:
        battery = psutil.sensors_battery()
    except Exception:
        return None

    if battery is None:
        return None

    seconds_left = battery.secsleft
    if isinstance(seconds_left, (int, float)) and seconds_left < 0:
        seconds_left = None

    return {
        "percent": _to_float(battery.percent),
        "plugged": battery.power_plugged,
        "seconds_left": seconds_left,
    }


def _collect_platform_info() -> dict[str, str | None]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "python_version": platform.python_version() if sys.version_info else None,
    }


def collect_system_info() -> dict[str, object]:
    return {
        "cpu": _collect_cpu_info(),
        "ram": _collect_ram_info(),
        "disks": _collect_disks_info(),
        "gpu": _collect_gpu_info(),
        "battery": _collect_battery_info(),
        "platform": _collect_platform_info(),
    }
