import psutil


def collect_current_metrics() -> dict[str, float]:
    return {
        "cpu_usage": psutil.cpu_percent(interval=1),
        "ram_usage": psutil.virtual_memory().percent,
        "disk_usage": psutil.disk_usage("C:\\").percent,
    }
