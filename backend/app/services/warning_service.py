from app.models.measurement import Measurement


WarningDict = dict[str, object]


def _append_threshold_warning(
    warnings: list[WarningDict],
    *,
    measurement: Measurement,
    metric: str,
    component: str,
    warning_threshold: float,
    critical_threshold: float,
    high_message: str,
    critical_message: str,
    direction: str = "high",
) -> None:
    value = getattr(measurement, metric, None)
    if value is None:
        return

    level: str | None = None
    threshold: float | None = None
    message: str | None = None

    if direction == "high":
        if value >= critical_threshold:
            level = "critical"
            threshold = critical_threshold
            message = critical_message
        elif value >= warning_threshold:
            level = "warning"
            threshold = warning_threshold
            message = high_message
    else:
        if value <= critical_threshold:
            level = "critical"
            threshold = critical_threshold
            message = critical_message
        elif value <= warning_threshold:
            level = "warning"
            threshold = warning_threshold
            message = high_message

    if level is None or threshold is None or message is None:
        return

    warnings.append(
        {
            "level": level,
            "component": component,
            "metric": metric,
            "value": value,
            "threshold": threshold,
            "message": message,
        }
    )


def calculate_health_score(
    measurement: Measurement,
    warnings: list[WarningDict],
) -> int:
    score = 100
    for warning in warnings:
        if warning["level"] == "critical":
            score -= 25
        else:
            score -= 10
    return max(0, min(100, score))


def build_component_status(warnings: list[WarningDict]) -> dict[str, str]:
    component_status = {
        "CPU": "ok",
        "GPU": "ok",
        "RAM": "ok",
        "Disk": "ok",
        "Cooling": "ok",
    }
    for warning in warnings:
        component = warning.get("component")
        level = warning.get("level")
        if component not in component_status or level not in ("warning", "critical"):
            continue
        if level == "critical":
            component_status[component] = "critical"
            continue
        if component_status[component] != "critical":
            component_status[component] = "warning"
    return component_status


def analyze_measurement(measurement: Measurement) -> dict[str, object]:
    warnings: list[WarningDict] = []

    _append_threshold_warning(
        warnings,
        measurement=measurement,
        metric="cpu_usage",
        component="CPU",
        warning_threshold=85,
        critical_threshold=95,
        high_message="High CPU usage",
        critical_message="Critical CPU usage",
    )
    _append_threshold_warning(
        warnings,
        measurement=measurement,
        metric="gpu_usage",
        component="GPU",
        warning_threshold=85,
        critical_threshold=95,
        high_message="High GPU usage",
        critical_message="Critical GPU usage",
    )
    _append_threshold_warning(
        warnings,
        measurement=measurement,
        metric="ram_usage",
        component="RAM",
        warning_threshold=85,
        critical_threshold=95,
        high_message="High RAM usage",
        critical_message="Critical RAM usage",
    )
    _append_threshold_warning(
        warnings,
        measurement=measurement,
        metric="disk_usage",
        component="Disk",
        warning_threshold=90,
        critical_threshold=97,
        high_message="High disk usage",
        critical_message="Critical disk usage",
    )
    _append_threshold_warning(
        warnings,
        measurement=measurement,
        metric="cpu_temperature",
        component="CPU",
        warning_threshold=75,
        critical_threshold=85,
        high_message="High CPU temperature",
        critical_message="Critical CPU temperature",
    )
    _append_threshold_warning(
        warnings,
        measurement=measurement,
        metric="gpu_temperature",
        component="GPU",
        warning_threshold=75,
        critical_threshold=85,
        high_message="High GPU temperature",
        critical_message="Critical GPU temperature",
    )
    _append_threshold_warning(
        warnings,
        measurement=measurement,
        metric="ram_temperature",
        component="RAM",
        warning_threshold=55,
        critical_threshold=70,
        high_message="High RAM temperature",
        critical_message="Critical RAM temperature",
    )
    _append_threshold_warning(
        warnings,
        measurement=measurement,
        metric="disk_temperature",
        component="Disk",
        warning_threshold=50,
        critical_threshold=60,
        high_message="High disk temperature",
        critical_message="Critical disk temperature",
    )
    _append_threshold_warning(
        warnings,
        measurement=measurement,
        metric="disk_life",
        component="Disk",
        warning_threshold=20,
        critical_threshold=10,
        high_message="Low disk life",
        critical_message="Critical disk life",
        direction="low",
    )

    if (
        measurement.system_fan_rpm is not None
        and measurement.system_fan_rpm <= 300
        and measurement.cpu_temperature is not None
        and measurement.cpu_temperature >= 70
    ):
        warnings.append(
            {
                "level": "warning",
                "component": "Cooling",
                "metric": "system_fan_rpm",
                "value": measurement.system_fan_rpm,
                "threshold": 300,
                "message": "Low system fan speed while CPU temperature is high",
            }
        )

    if (
        measurement.system_fan_rpm is not None
        and measurement.system_fan_rpm <= 300
        and measurement.gpu_temperature is not None
        and measurement.gpu_temperature >= 70
    ):
        warnings.append(
            {
                "level": "warning",
                "component": "Cooling",
                "metric": "system_fan_rpm",
                "value": measurement.system_fan_rpm,
                "threshold": 300,
                "message": "Low system fan speed while GPU temperature is high",
            }
        )

    status = "ok"
    if any(warning["level"] == "critical" for warning in warnings):
        status = "critical"
    elif warnings:
        status = "warning"

    return {
        "status": status,
        "health_score": calculate_health_score(measurement, warnings),
        "warnings": warnings,
    }
