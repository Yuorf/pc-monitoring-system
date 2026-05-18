import subprocess

import psutil

from app.services.external_tools_service import get_hidden_subprocess_kwargs


def _collect_gpu_usage() -> float | None:
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
            **get_hidden_subprocess_kwargs(),
        )
        output = result.stdout.strip()
        if not output:
            return None
        return float(output)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def collect_current_metrics() -> dict[str, float | None]:
    return {
        "cpu_usage": psutil.cpu_percent(interval=1),
        "gpu_usage": _collect_gpu_usage(),
        "ram_usage": psutil.virtual_memory().percent,
        "disk_usage": psutil.disk_usage("C:\\").percent,
    }
