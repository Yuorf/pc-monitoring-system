from app.models.measurement import Measurement


def analyze_measurement(measurement: Measurement) -> dict[str, object]:
    warnings = []
    if measurement.cpu_usage >= 95:
        warnings.append("Critical CPU usage")
    elif measurement.cpu_usage >= 85:
        warnings.append("High CPU usage")
    if measurement.gpu_usage is not None and measurement.gpu_usage >= 95:
        warnings.append("Critical GPU usage")
    elif measurement.gpu_usage is not None and measurement.gpu_usage >= 85:
        warnings.append("High GPU usage")
    if measurement.ram_usage >= 95:
        warnings.append("Critical RAM usage")
    elif measurement.ram_usage >= 85:
        warnings.append("High RAM usage")
    if measurement.disk_usage >= 97:
        warnings.append("Critical disk usage")
    elif measurement.disk_usage >= 90:
        warnings.append("High disk usage")

    status = "ok"
    if any(warning.startswith("Critical") for warning in warnings):
        status = "critical"
    elif warnings:
        status = "warning"

    return {
        "status": status,
        "warnings": warnings,
    }
