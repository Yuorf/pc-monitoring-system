from app.models.measurement import Measurement


def analyze_measurement(measurement: Measurement) -> dict[str, object]:
    warnings = []
    if measurement.cpu_usage >= 85:
        warnings.append("High CPU usage")
    if measurement.ram_usage >= 85:
        warnings.append("High RAM usage")
    if measurement.disk_usage >= 90:
        warnings.append("High disk usage")

    return {
        "status": "warning" if warnings else "ok",
        "warnings": warnings,
    }
