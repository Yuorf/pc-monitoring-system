import asyncio
from datetime import datetime

from fastapi import Body, FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import inspect, text

from app.core.database import (
    Base,
    DATABASE_FILE,
    DATABASE_TYPE,
    DATABASE_URL_CONFIGURED,
    SessionLocal,
    engine,
)
from app.core.config import settings
from app.models.device import Device
from app.models.measurement import Measurement
from app.services.external_tools_service import (
    LHM_PROCESS_NAME,
    check_external_tools_health,
    start_lhm_if_needed,
)
from app.services.hardware_sensors import collect_hardware_sensors, extract_key_metrics
from app.services.ml_prediction_service import (
    get_smart_model_info,
    load_smart_model_artifact,
    predict_current_smart_failure,
    predict_smart_failure,
    sanitize_smart_drive_for_status,
)
from app.services.smart_service import collect_smart_data
from app.services.system_info import collect_system_info
from app.services.system_metrics import collect_current_metrics
from app.services.warning_service import (
    analyze_measurement,
    build_component_status,
    build_recommendations,
)

app = FastAPI(title=settings.APP_NAME)

MEASUREMENT_COLUMN_TYPES = {
    "gpu_usage": "FLOAT",
    "cpu_temperature": "FLOAT",
    "gpu_temperature": "FLOAT",
    "ram_temperature": "FLOAT",
    "disk_temperature": "FLOAT",
    "cpu_power": "FLOAT",
    "gpu_power": "FLOAT",
    "system_fan_rpm": "FLOAT",
    "disk_life": "FLOAT",
    "disk_power_on_hours": "INTEGER",
}

SENSOR_BUCKET_NAMES = (
    "temperatures",
    "fans",
    "voltages",
    "powers",
    "clocks",
    "loads",
    "controls",
    "data",
)

EXTERNAL_TOOLS_STATUS: dict[str, dict[str, object]] = {
    "libre_hardware_monitor": {
        "status": "not_started",
        "process_name": LHM_PROCESS_NAME,
    }
}


class SmartPredictionRequest(BaseModel):
    capacity_bytes: int | None = None
    smart_1_raw: float | None = 0
    smart_5_raw: float | None = 0
    smart_7_raw: float | None = 0
    smart_9_raw: float | None = 0
    smart_12_raw: float | None = 0
    smart_187_raw: float | None = 0
    smart_188_raw: float | None = 0
    smart_194_raw: float | None = 0
    smart_196_raw: float | None = 0
    smart_197_raw: float | None = 0
    smart_198_raw: float | None = 0
    smart_199_raw: float | None = 0


def measurement_to_dict(
    measurement: Measurement,
    *,
    include_device_id: bool = True,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": measurement.id,
        "cpu_usage": measurement.cpu_usage,
        "gpu_usage": measurement.gpu_usage,
        "ram_usage": measurement.ram_usage,
        "disk_usage": measurement.disk_usage,
        "cpu_temperature": measurement.cpu_temperature,
        "gpu_temperature": measurement.gpu_temperature,
        "ram_temperature": measurement.ram_temperature,
        "disk_temperature": measurement.disk_temperature,
        "cpu_power": measurement.cpu_power,
        "gpu_power": measurement.gpu_power,
        "system_fan_rpm": measurement.system_fan_rpm,
        "disk_life": measurement.disk_life,
        "disk_power_on_hours": measurement.disk_power_on_hours,
        "recorded_at": measurement.recorded_at,
    }
    if include_device_id:
        payload["device_id"] = measurement.device_id
    return payload


def _measurement_to_dashboard_history_item(
    measurement: Measurement,
) -> dict[str, object]:
    return {
        "id": measurement.id,
        "recorded_at": (
            measurement.recorded_at.isoformat()
            if measurement.recorded_at is not None
            else None
        ),
        "cpu_usage": measurement.cpu_usage,
        "gpu_usage": measurement.gpu_usage,
        "ram_usage": measurement.ram_usage,
        "disk_usage": measurement.disk_usage,
        "cpu_temperature": measurement.cpu_temperature,
        "gpu_temperature": measurement.gpu_temperature,
        "ram_temperature": measurement.ram_temperature,
        "disk_temperature": measurement.disk_temperature,
        "cpu_power": measurement.cpu_power,
        "gpu_power": measurement.gpu_power,
        "system_fan_rpm": measurement.system_fan_rpm,
        "disk_life": measurement.disk_life,
        "disk_power_on_hours": measurement.disk_power_on_hours,
    }


def _get_dashboard_measurements(
    db,
    device_id: int,
    limit: int,
) -> list[Measurement]:
    measurements = (
        db.query(Measurement)
        .filter(Measurement.device_id == device_id)
        .order_by(Measurement.recorded_at.desc())
        .limit(limit)
        .all()
    )

    return list(reversed(measurements))


def _round_chart_value(value: object) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, 2)

    numeric_value = _to_float(value)
    if numeric_value is None:
        return None
    return round(numeric_value, 2)


def _build_chart_points(
    measurements: list[Measurement],
    field_name: str,
) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []

    for measurement in measurements:
        points.append(
            {
                "time": (
                    measurement.recorded_at.isoformat()
                    if measurement.recorded_at is not None
                    else None
                ),
                "value": _round_chart_value(getattr(measurement, field_name, None)),
            }
        )

    return points


def _build_chart_series(
    measurements: list[Measurement],
    series_config: list[dict[str, str]],
) -> list[dict[str, object]]:
    return [
        {
            "key": item["key"],
            "name": item["name"],
            "points": _build_chart_points(measurements, item["key"]),
        }
        for item in series_config
    ]


def _build_dashboard_charts_payload(
    measurements: list[Measurement],
    device_id: int | None,
    limit: int,
) -> dict[str, object]:
    charts_config = {
        "usage": {
            "title": "Нагрузка компонентов",
            "unit": "%",
            "type": "line",
            "series": [
                {"key": "cpu_usage", "name": "CPU"},
                {"key": "gpu_usage", "name": "GPU"},
                {"key": "ram_usage", "name": "RAM"},
                {"key": "disk_usage", "name": "Disk"},
            ],
        },
        "temperatures": {
            "title": "Температуры компонентов",
            "unit": "°C",
            "type": "line",
            "series": [
                {"key": "cpu_temperature", "name": "CPU"},
                {"key": "gpu_temperature", "name": "GPU"},
                {"key": "ram_temperature", "name": "RAM"},
                {"key": "disk_temperature", "name": "Disk"},
            ],
        },
        "power": {
            "title": "Потребление мощности",
            "unit": "W",
            "type": "line",
            "series": [
                {"key": "cpu_power", "name": "CPU"},
                {"key": "gpu_power", "name": "GPU"},
            ],
        },
        "cooling": {
            "title": "Скорость вентиляторов",
            "unit": "RPM",
            "type": "line",
            "series": [
                {"key": "system_fan_rpm", "name": "System Fan"},
            ],
        },
        "disk_health": {
            "title": "Состояние накопителя",
            "unit": "",
            "type": "line",
            "series": [
                {"key": "disk_life", "name": "Disk Life"},
                {"key": "disk_power_on_hours", "name": "Power On Hours"},
            ],
        },
    }

    charts: dict[str, object] = {}
    for chart_key, chart_config in charts_config.items():
        charts[chart_key] = {
            "title": chart_config["title"],
            "unit": chart_config["unit"],
            "type": chart_config["type"],
            "series": _build_chart_series(measurements, chart_config["series"]),
        }

    return {
        "device_id": device_id,
        "limit": limit,
        "count": len(measurements),
        "updated_at": f"{datetime.utcnow().isoformat()}Z",
        "charts": charts,
    }


def _safe_error_text(error: Exception) -> str:
    error_text = str(error).strip()
    return error_text or error.__class__.__name__


def _extract_system_component_name(
    system_info: object,
    component_key: str,
    fallback: str,
) -> str:
    if not isinstance(system_info, dict):
        return fallback

    component = system_info.get(component_key)
    if not isinstance(component, dict):
        return fallback

    name = component.get("name")
    if not isinstance(name, str):
        return fallback

    normalized_name = name.strip()
    return normalized_name or fallback


def _create_default_device(db) -> Device | None:
    cpu_name = "Unknown CPU"
    gpu_name = "Unknown GPU"
    try:
        system_info = collect_system_info()
        cpu_name = _extract_system_component_name(
            system_info,
            "cpu",
            cpu_name,
        )
        gpu_name = _extract_system_component_name(
            system_info,
            "gpu",
            gpu_name,
        )
    except Exception as error:
        print(
            "Failed to collect system info for default device creation: "
            f"{_safe_error_text(error)}"
        )

    try:
        device = Device(
            name="Local PC",
            cpu=cpu_name,
            gpu=gpu_name,
            created_at=datetime.utcnow(),
        )
        db.add(device)
        db.commit()
        db.refresh(device)
        print(
            "Created default device for local monitoring: "
            f"name={device.name}, cpu={device.cpu}, gpu={device.gpu}"
        )
        return device
    except Exception as error:
        db.rollback()
        print(f"Failed to create default device: {_safe_error_text(error)}")
        return None


def get_default_device(db) -> Device | None:
    device = db.query(Device).order_by(Device.id.asc()).first()
    if device is not None:
        return device
    return _create_default_device(db)


def ensure_default_device_exists() -> None:
    try:
        with SessionLocal() as db:
            get_default_device(db)
    except Exception as error:
        print(f"Failed to ensure default device exists: {_safe_error_text(error)}")


def _unknown_component_status() -> dict[str, str]:
    return {
        "CPU": "unknown",
        "GPU": "unknown",
        "RAM": "unknown",
        "Disk": "unknown",
        "Cooling": "unknown",
    }


def _build_status_measurement(
    metrics: dict[str, object] | None,
    key_metrics: dict[str, object] | None,
) -> Measurement:
    metrics = metrics or {}
    key_metrics = key_metrics or {}
    measurement = Measurement(
        device_id=None,
        cpu_usage=metrics.get("cpu_usage"),
        gpu_usage=metrics.get("gpu_usage"),
        ram_usage=metrics.get("ram_usage"),
        disk_usage=metrics.get("disk_usage"),
        cpu_temperature=key_metrics.get("cpu_temperature"),
        gpu_temperature=key_metrics.get("gpu_temperature"),
        ram_temperature=key_metrics.get("ram_temperature"),
        disk_temperature=key_metrics.get("disk_temperature"),
        cpu_power=key_metrics.get("cpu_power"),
        gpu_power=key_metrics.get("gpu_power"),
        system_fan_rpm=key_metrics.get("system_fan_rpm"),
        disk_life=key_metrics.get("disk_life"),
        disk_power_on_hours=key_metrics.get("disk_power_on_hours"),
        recorded_at=datetime.utcnow(),
    )
    return measurement


def _build_system_status_analysis(
    metrics: dict[str, object] | None,
    sensors: dict[str, object] | None,
) -> tuple[dict[str, object], dict[str, object]]:
    if metrics is None and sensors is None:
        warnings_payload = {
            "available": False,
            "status": "unknown",
            "health_score": None,
            "components": _unknown_component_status(),
            "items": [],
            "error": "System metrics and sensors are unavailable.",
        }
        recommendations_payload = {
            "available": False,
            "items": [],
            "error": "System metrics and sensors are unavailable.",
        }
        return warnings_payload, recommendations_payload

    try:
        key_metrics = extract_key_metrics(sensors) if sensors is not None else {}
        analysis = analyze_measurement(_build_status_measurement(metrics, key_metrics))
        warnings_payload = {
            "available": True,
            "status": analysis["status"],
            "health_score": analysis["health_score"],
            "components": build_component_status(analysis["warnings"]),
            "items": analysis["warnings"],
        }
        recommendations_payload = {
            "available": True,
            "items": build_recommendations(analysis["warnings"]),
        }
        return warnings_payload, recommendations_payload
    except Exception as error:
        error_text = _safe_error_text(error)
        warnings_payload = {
            "available": False,
            "status": "unknown",
            "health_score": None,
            "components": _unknown_component_status(),
            "items": [],
            "error": error_text,
        }
        recommendations_payload = {
            "available": False,
            "items": [],
            "error": error_text,
        }
        return warnings_payload, recommendations_payload


def _build_compact_smart_payload(smart_data: object) -> dict[str, object]:
    if not isinstance(smart_data, dict):
        return {
            "available": True,
            "drives": [],
            "sources": None,
        }

    raw_drives = smart_data.get("drives")
    compact_drives: list[dict[str, object]] = []
    if isinstance(raw_drives, list):
        for drive in raw_drives:
            compact_drive = sanitize_smart_drive_for_status(drive)
            if compact_drive is not None:
                compact_drives.append(compact_drive)

    return {
        "available": True,
        "drives": compact_drives,
        "sources": smart_data.get("sources"),
    }


def _to_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _sensor_name(sensor: dict[str, object]) -> str:
    return str(sensor.get("name", "")).lower()


def _sensor_text(sensor: dict[str, object]) -> str:
    return " ".join(
        str(value).lower()
        for value in (
            sensor.get("component"),
            sensor.get("name"),
            sensor.get("source"),
            sensor.get("unit"),
        )
        if value is not None
    )


def _match_keywords(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _collect_compact_sensors(
    sensors_data: dict[str, object],
    bucket: str,
    *,
    component: str | None = None,
    include_keywords: tuple[str, ...] = (),
    exclude_keywords: tuple[str, ...] = (),
    required_unit: str | None = None,
) -> list[dict[str, object]]:
    raw_sensors = sensors_data.get(bucket, [])
    if not isinstance(raw_sensors, list):
        return []

    matched: list[dict[str, object]] = []
    for sensor in raw_sensors:
        if not isinstance(sensor, dict):
            continue
        if component and str(sensor.get("component")).lower() != component.lower():
            continue

        text = _sensor_text(sensor)
        if include_keywords and not _match_keywords(text, include_keywords):
            continue
        if exclude_keywords and _match_keywords(text, exclude_keywords):
            continue
        if required_unit is not None and str(sensor.get("unit", "")).strip() != required_unit:
            continue
        if _to_float(sensor.get("value")) is None:
            continue
        matched.append(sensor)

    return matched


def _max_sensor_value(sensors: list[dict[str, object]]) -> float | None:
    values = [
        value
        for sensor in sensors
        if (value := _to_float(sensor.get("value"))) is not None
    ]
    if not values:
        return None
    return max(values)


def _is_nvidia_gpu_sensor(sensor: dict[str, object]) -> bool:
    sensor_id = str(sensor.get("sensor_id", "")).lower()
    source = str(sensor.get("source", "")).lower()
    name = _sensor_name(sensor)
    return (
        "/gpu-nvidia/" in sensor_id
        or source == "nvidia-smi"
        or "nvidia" in name
    )


def _is_excluded_gpu_memory_sensor(sensor: dict[str, object]) -> bool:
    name = _sensor_name(sensor)
    excluded_name_parts = (
        "d3d shared memory",
        "d3d dedicated memory",
        "shared memory",
    )
    return any(excluded_name_part in name for excluded_name_part in excluded_name_parts)


def _matches_gpu_memory_sensor_name(
    sensor: dict[str, object],
    *,
    exact_names: tuple[str, ...],
    contains_names: tuple[str, ...],
) -> bool:
    name = _sensor_name(sensor)
    normalized_name = " ".join(name.split())
    if normalized_name in exact_names:
        return True
    return any(contains_name in normalized_name for contains_name in contains_names)


def _pick_gpu_memory_value(
    sensors: list[dict[str, object]],
    *,
    exact_names: tuple[str, ...],
    contains_names: tuple[str, ...],
) -> float | None:
    filtered_sensors = [
        sensor for sensor in sensors if not _is_excluded_gpu_memory_sensor(sensor)
    ]
    if not filtered_sensors:
        return None

    prioritized_groups = [
        [
            sensor
            for sensor in filtered_sensors
            if _is_nvidia_gpu_sensor(sensor)
            and _matches_gpu_memory_sensor_name(
                sensor,
                exact_names=exact_names,
                contains_names=contains_names,
            )
        ],
        [
            sensor
            for sensor in filtered_sensors
            if _matches_gpu_memory_sensor_name(
                sensor,
                exact_names=exact_names,
                contains_names=contains_names,
            )
        ],
        [
            sensor for sensor in filtered_sensors if _is_nvidia_gpu_sensor(sensor)
        ],
        filtered_sensors,
    ]

    for group in prioritized_groups:
        value = _max_sensor_value(group)
        if value is not None:
            return value

    return None


def _round_metric_value(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def _build_compact_sensors_payload(sensors_data: dict[str, object]) -> dict[str, object]:
    summary = {
        "cpu_temperature": None,
        "gpu_temperature": None,
        "ram_temperature": None,
        "disk_temperature": None,
        "cpu_power": None,
        "gpu_power": None,
        "system_fan_rpm": None,
        "gpu_fan_percent": None,
        "gpu_memory_used_mb": None,
        "gpu_memory_total_mb": None,
    }
    counts = {
        bucket: 0 for bucket in SENSOR_BUCKET_NAMES
    }

    if not isinstance(sensors_data, dict):
        return {
            "available": True,
            "sources": None,
            "summary": summary,
            "counts": counts,
        }

    key_metrics = extract_key_metrics(sensors_data)
    summary.update(
        {
            "cpu_temperature": key_metrics.get("cpu_temperature"),
            "gpu_temperature": key_metrics.get("gpu_temperature"),
            "ram_temperature": key_metrics.get("ram_temperature"),
            "disk_temperature": key_metrics.get("disk_temperature"),
            "cpu_power": key_metrics.get("cpu_power"),
            "gpu_power": key_metrics.get("gpu_power"),
            "system_fan_rpm": key_metrics.get("system_fan_rpm"),
        }
    )

    gpu_fan_sensors = _collect_compact_sensors(
        sensors_data,
        "fans",
        component="GPU",
        required_unit="%",
    )
    if not gpu_fan_sensors:
        gpu_fan_sensors = _collect_compact_sensors(
            sensors_data,
            "controls",
            component="GPU",
            required_unit="%",
        )
    summary["gpu_fan_percent"] = _round_metric_value(_max_sensor_value(gpu_fan_sensors))

    gpu_data_sensors = _collect_compact_sensors(sensors_data, "data", component="GPU")
    summary["gpu_memory_used_mb"] = _round_metric_value(
        _pick_gpu_memory_value(
            gpu_data_sensors,
            exact_names=("gpu memory used",),
            contains_names=("gpu memory used", "memory used", "vram used"),
        )
    )
    summary["gpu_memory_total_mb"] = _round_metric_value(
        _pick_gpu_memory_value(
            gpu_data_sensors,
            exact_names=("gpu memory total",),
            contains_names=("gpu memory total", "memory total", "vram total"),
        )
    )

    for bucket in SENSOR_BUCKET_NAMES:
        bucket_value = sensors_data.get(bucket)
        counts[bucket] = len(bucket_value) if isinstance(bucket_value, list) else 0

    sources = sensors_data.get("sources")
    return {
        "available": True,
        "sources": sources if isinstance(sources, dict) else None,
        "summary": summary,
        "counts": counts,
    }


def _copy_lhm_status_payload() -> dict[str, object]:
    status_payload = EXTERNAL_TOOLS_STATUS.get("libre_hardware_monitor")
    if isinstance(status_payload, dict):
        return status_payload.copy()
    return {
        "status": "unknown",
        "process_name": LHM_PROCESS_NAME,
    }


def _merge_lhm_health_payload(runtime_payload: object) -> dict[str, object]:
    merged_payload = _safe_dict(runtime_payload)
    startup_payload = _copy_lhm_status_payload()

    for field_name in (
        "status",
        "process_name",
        "exe_path",
        "checked_paths",
        "error",
    ):
        field_value = startup_payload.get(field_name)
        if field_value in (None, "", []):
            continue
        merged_payload[field_name] = field_value

    if "process_name" not in merged_payload:
        merged_payload["process_name"] = LHM_PROCESS_NAME

    return merged_payload


def _build_external_tools_payload() -> dict[str, object]:
    runtime_payload = _safe_dict(check_external_tools_health())
    smartctl_payload = runtime_payload.get("smartctl")
    return {
        "libre_hardware_monitor": _merge_lhm_health_payload(
            runtime_payload.get("libre_hardware_monitor")
        ),
        "smartctl": _safe_dict(smartctl_payload),
    }


def _safe_get_nested(
    payload: object,
    *keys: str,
    default: object = None,
) -> object:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return default
        if key not in current:
            return default
        current = current[key]
    return current


def _safe_dict(value: object) -> dict[str, object]:
    return value.copy() if isinstance(value, dict) else {}


def _safe_list(value: object) -> list[object]:
    return value.copy() if isinstance(value, list) else []


def _safe_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _round_optional_number(value: object, digits: int = 2) -> float | None:
    numeric_value = _to_float(value)
    if numeric_value is None:
        return None
    return round(numeric_value, digits)


def _normalize_dashboard_status(value: object) -> str:
    status_value = _safe_text(value)
    if status_value in {"ok", "warning", "critical", "unknown"}:
        return status_value
    return "unknown"


def _collect_system_info_safe() -> dict[str, object]:
    try:
        system_info = collect_system_info()
        return system_info if isinstance(system_info, dict) else {}
    except Exception:
        return {}


def _build_dashboard_card(
    *,
    card_id: str,
    title: str,
    status: object,
    primary_value: object,
    primary_unit: str,
    secondary_value: object,
    secondary_unit: str,
    details: dict[str, object],
) -> dict[str, object]:
    return {
        "id": card_id,
        "title": title,
        "status": _normalize_dashboard_status(status),
        "primary_value": _round_optional_number(primary_value),
        "primary_unit": primary_unit,
        "secondary_value": _round_optional_number(secondary_value),
        "secondary_unit": secondary_unit,
        "details": details,
    }


def _has_high_risk_drive(drives: list[object]) -> bool:
    for drive in drives:
        if not isinstance(drive, dict):
            continue
        health_status = _safe_text(drive.get("health_status"))
        if health_status and health_status.upper() not in {"PASSED", "OK"}:
            return True
    return False


def _get_dashboard_drive_name(drive_payload: object) -> str:
    if not isinstance(drive_payload, dict):
        return "накопитель"
    return (
        _safe_text(drive_payload.get("model"))
        or _safe_text(drive_payload.get("name"))
        or "накопитель"
    )


def _build_dashboard_score_detail(
    *,
    label: str,
    penalty: int,
    reason: str,
    component: str,
) -> dict[str, object]:
    return {
        "label": label,
        "penalty": penalty,
        "reason": reason,
        "component": component,
    }


def _build_dashboard_overall_payload(
    warnings_payload: object,
    ml_prediction_payload: object,
    smart_drives: list[object],
    external_tools_payload: object,
    cards: list[dict[str, object]],
) -> dict[str, object]:
    score = 100
    score_details: list[dict[str, object]] = []
    problematic_drive_names: set[str] = set()
    critical_non_disk_count = sum(
        1
        for card in cards
        if isinstance(card, dict)
        and card.get("id") != "disk"
        and card.get("status") in {"critical", "error"}
    )
    external_error_count = 0

    def add_detail(
        *,
        label: str,
        penalty: int,
        reason: str,
        component: str,
    ) -> None:
        nonlocal score
        score -= penalty
        score_details.append(
            _build_dashboard_score_detail(
                label=label,
                penalty=penalty,
                reason=reason,
                component=component,
            )
        )

    prediction_payload = (
        ml_prediction_payload.get("prediction")
        if isinstance(ml_prediction_payload, dict)
        else None
    )
    source_drive_payload = (
        ml_prediction_payload.get("source_drive")
        if isinstance(ml_prediction_payload, dict)
        and isinstance(ml_prediction_payload.get("source_drive"), dict)
        else None
    )
    ml_status = _safe_text(
        prediction_payload.get("status")
        if isinstance(prediction_payload, dict)
        else None
    )
    ml_risk_percent = _to_float(
        prediction_payload.get("risk_percent")
        if isinstance(prediction_payload, dict)
        else None
    )

    if ml_status == "high_risk" or (
        isinstance(ml_risk_percent, (int, float)) and ml_risk_percent >= 50
    ):
        drive_name = _get_dashboard_drive_name(source_drive_payload)
        problematic_drive_names.add(drive_name)
        add_detail(
            label="Повышенный риск по модели",
            penalty=15,
            reason=f"Повышенный риск по SMART-признакам: {drive_name}.",
            component="Disk",
        )

    for drive_payload in smart_drives:
        if not isinstance(drive_payload, dict):
            continue

        drive_name = _get_dashboard_drive_name(drive_payload)
        reallocated = _to_float(
            drive_payload.get("reallocated_sectors_count")
            or drive_payload.get("reallocated_sectors")
            or drive_payload.get("reallocated_sector_count")
        )
        pending = _to_float(drive_payload.get("current_pending_sector_count"))
        uncorrectable = _to_float(
            drive_payload.get("offline_uncorrectable")
            or drive_payload.get("reported_uncorrectable_errors")
        )
        crc_errors = _to_float(drive_payload.get("udma_crc_error_count"))

        if isinstance(reallocated, (int, float)) and reallocated > 0:
            problematic_drive_names.add(drive_name)
            add_detail(
                label="Переназначенные сектора",
                penalty=5,
                reason=(
                    f"У накопителя {drive_name} обнаружены "
                    f"переназначенные сектора: {int(reallocated)}."
                ),
                component="Disk",
            )
        if isinstance(pending, (int, float)) and pending > 0:
            problematic_drive_names.add(drive_name)
            add_detail(
                label="Ожидающие сектора",
                penalty=10,
                reason=(
                    f"У накопителя {drive_name} есть ожидающие сектора: "
                    f"{int(pending)}."
                ),
                component="Disk",
            )
        if isinstance(uncorrectable, (int, float)) and uncorrectable > 0:
            problematic_drive_names.add(drive_name)
            add_detail(
                label="Некорректируемые ошибки",
                penalty=10,
                reason=(
                    f"У накопителя {drive_name} есть некорректируемые "
                    f"SMART-ошибки."
                ),
                component="Disk",
            )
        if isinstance(crc_errors, (int, float)) and crc_errors > 0:
            problematic_drive_names.add(drive_name)
            add_detail(
                label="CRC ошибки",
                penalty=2,
                reason=f"У накопителя {drive_name} зафиксированы CRC-ошибки.",
                component="Disk",
            )

    warning_items = _safe_list(
        warnings_payload.get("items") if isinstance(warnings_payload, dict) else []
    )
    for warning_payload in warning_items:
        if not isinstance(warning_payload, dict):
            continue

        component = _safe_text(warning_payload.get("component")) or "System"
        metric_name = (_safe_text(warning_payload.get("metric")) or "").lower()
        level = (_safe_text(warning_payload.get("level")) or "warning").lower()

        if component == "Disk" and metric_name == "ml_smart_failure_prediction":
            continue

        if "temp" in metric_name or "temperature" in metric_name or "thermal" in metric_name:
            add_detail(
                label="Температурное предупреждение",
                penalty=20 if level == "critical" else 10,
                reason=(
                    _safe_text(warning_payload.get("message"))
                    or f"Есть температурное предупреждение по компоненту {component}."
                ),
                component=component,
            )
        elif component in {"CPU", "GPU", "RAM", "Cooling"} and level in {"warning", "critical"}:
            add_detail(
                label="Предупреждение по компоненту",
                penalty=15 if level == "critical" else 8,
                reason=(
                    _safe_text(warning_payload.get("message"))
                    or f"Есть предупреждение по компоненту {component}."
                ),
                component=component,
            )

    lhm_status = _safe_text(
        _safe_get_nested(
            external_tools_payload,
            "libre_hardware_monitor",
            "status",
            default=None,
        )
    )
    if lhm_status == "error":
        external_error_count += 1
        add_detail(
            label="Ошибка датчиков оборудования",
            penalty=20,
            reason="Не удалось получить данные от датчиков оборудования.",
            component="Sensors",
        )
    elif lhm_status == "not_found":
        add_detail(
            label="Датчики оборудования недоступны",
            penalty=10,
            reason="Источник данных датчиков оборудования не найден.",
            component="Sensors",
        )

    smartctl_status = _safe_text(
        _safe_get_nested(external_tools_payload, "smartctl", "status", default=None)
    )
    if smartctl_status == "error":
        external_error_count += 1
        add_detail(
            label="Ошибка SMART-диагностики",
            penalty=15,
            reason="Не удалось получить SMART-данные через smartctl.",
            component="SMART",
        )
    elif smartctl_status == "not_found":
        add_detail(
            label="SMART-диагностика недоступна",
            penalty=10,
            reason="Утилита smartctl не найдена.",
            component="SMART",
        )

    score = max(0, min(100, score))
    if (
        external_error_count >= 1
        or critical_non_disk_count >= 2
        or (critical_non_disk_count >= 1 and len(problematic_drive_names) >= 1)
        or len(problematic_drive_names) >= 2
    ):
        status = "critical"
    elif score_details:
        status = "warning"
    else:
        status = "ok"

    return {
        "status": status,
        "health_score": int(round(score)),
        "reason": (
            score_details[0]["reason"]
            if score_details
            else "Критичных предупреждений не обнаружено."
        ),
        "score_details": score_details,
    }


def _build_dashboard_payload(
    system_status_payload: object,
    device: Device | None = None,
    system_info_payload: object = None,
) -> dict[str, object]:
    metrics_data = _safe_dict(
        _safe_get_nested(system_status_payload, "metrics", "data", default={})
    )
    sensors_summary = _safe_dict(
        _safe_get_nested(system_status_payload, "sensors", "summary", default={})
    )
    smart_payload = _safe_dict(_safe_get_nested(system_status_payload, "smart", default={}))
    warnings_payload = _safe_dict(
        _safe_get_nested(system_status_payload, "warnings", default={})
    )
    recommendations_payload = _safe_dict(
        _safe_get_nested(system_status_payload, "recommendations", default={})
    )
    ml_prediction_payload = _safe_dict(
        _safe_get_nested(system_status_payload, "ml_prediction", default={})
    )
    prediction_payload = _safe_dict(
        _safe_get_nested(ml_prediction_payload, "prediction", default={})
    )
    components = _safe_dict(_safe_get_nested(warnings_payload, "components", default={}))
    smart_drives = _safe_list(smart_payload.get("drives"))
    external_tools_payload = _safe_dict(
        _safe_get_nested(system_status_payload, "external_tools", default={})
    )
    configuration_payload = _build_dashboard_configuration_payload(
        system_info_payload,
        drives_count=len(smart_drives),
    )

    ml_risk_percent = _round_optional_number(prediction_payload.get("risk_percent"))
    ml_status = _safe_text(prediction_payload.get("status"))
    high_risk = bool(
        ml_status == "high_risk"
        or (
            isinstance(ml_risk_percent, (int, float))
            and ml_risk_percent >= 50
        )
        or _has_high_risk_drive(smart_drives)
    )

    cards = [
        _build_dashboard_card(
            card_id="cpu",
            title="CPU",
            status=components.get("CPU"),
            primary_value=metrics_data.get("cpu_usage"),
            primary_unit="%",
            secondary_value=sensors_summary.get("cpu_temperature"),
            secondary_unit="°C",
            details={
                "usage_percent": _round_optional_number(metrics_data.get("cpu_usage")),
                "temperature_celsius": _round_optional_number(
                    sensors_summary.get("cpu_temperature")
                ),
                "power_watts": _round_optional_number(sensors_summary.get("cpu_power")),
            },
        ),
        _build_dashboard_card(
            card_id="gpu",
            title="GPU",
            status=components.get("GPU"),
            primary_value=metrics_data.get("gpu_usage"),
            primary_unit="%",
            secondary_value=sensors_summary.get("gpu_temperature"),
            secondary_unit="°C",
            details={
                "usage_percent": _round_optional_number(metrics_data.get("gpu_usage")),
                "temperature_celsius": _round_optional_number(
                    sensors_summary.get("gpu_temperature")
                ),
                "power_watts": _round_optional_number(sensors_summary.get("gpu_power")),
                "fan_percent": _round_optional_number(
                    sensors_summary.get("gpu_fan_percent")
                ),
                "memory_used_mb": _round_optional_number(
                    sensors_summary.get("gpu_memory_used_mb")
                ),
                "memory_total_mb": _round_optional_number(
                    sensors_summary.get("gpu_memory_total_mb")
                ),
            },
        ),
        _build_dashboard_card(
            card_id="ram",
            title="RAM",
            status=components.get("RAM"),
            primary_value=metrics_data.get("ram_usage"),
            primary_unit="%",
            secondary_value=sensors_summary.get("ram_temperature"),
            secondary_unit="°C",
            details={
                "usage_percent": _round_optional_number(metrics_data.get("ram_usage")),
                "temperature_celsius": _round_optional_number(
                    sensors_summary.get("ram_temperature")
                ),
            },
        ),
        _build_dashboard_card(
            card_id="disk",
            title="Disk",
            status=components.get("Disk"),
            primary_value=metrics_data.get("disk_usage"),
            primary_unit="%",
            secondary_value=sensors_summary.get("disk_temperature"),
            secondary_unit="°C",
            details={
                "usage_percent": _round_optional_number(metrics_data.get("disk_usage")),
                "temperature_celsius": _round_optional_number(
                    sensors_summary.get("disk_temperature")
                ),
                "drives_count": len(smart_drives),
                "high_risk": high_risk,
            },
        ),
    ]
    overall_payload = _build_dashboard_overall_payload(
        warnings_payload,
        ml_prediction_payload,
        smart_drives,
        external_tools_payload,
        cards,
    )

    return {
        "device": _build_dashboard_device_payload(device, configuration_payload),
        "configuration": configuration_payload,
        "overall": {
            "status": _normalize_dashboard_status(overall_payload.get("status")),
            "health_score": _round_optional_number(overall_payload.get("health_score")),
            "reason": _safe_text(overall_payload.get("reason")),
            "score_details": _safe_list(overall_payload.get("score_details")),
            "updated_at": f"{datetime.utcnow().isoformat()}Z",
        },
        "cards": cards,
        "smart": {
            "drives": smart_drives,
            "sources": (
                smart_payload.get("sources")
                if isinstance(smart_payload.get("sources"), dict)
                else None
            ),
        },
        "ml_prediction": {
            "available": bool(ml_prediction_payload.get("available")),
            "risk_percent": ml_risk_percent,
            "status": ml_status,
            "source_drive": (
                ml_prediction_payload.get("source_drive")
                if isinstance(ml_prediction_payload.get("source_drive"), dict)
                else None
            ),
            "recommendation": _safe_text(prediction_payload.get("recommendation")),
        },
        "warnings": {
            "status": _normalize_dashboard_status(warnings_payload.get("status")),
            "items": _safe_list(warnings_payload.get("items")),
        },
        "recommendations": {
            "items": _safe_list(recommendations_payload.get("items")),
        },
        "external_tools": external_tools_payload,
    }


def _build_dashboard_configuration_payload(
    system_info_payload: object,
    *,
    drives_count: int = 0,
) -> dict[str, object]:
    cpu_payload = _safe_dict(_safe_get_nested(system_info_payload, "cpu", default={}))
    gpu_payload = _safe_dict(_safe_get_nested(system_info_payload, "gpu", default={}))
    ram_payload = _safe_dict(_safe_get_nested(system_info_payload, "ram", default={}))
    motherboard_payload = _safe_dict(
        _safe_get_nested(system_info_payload, "motherboard", default={})
    )
    bios_payload = _safe_dict(_safe_get_nested(system_info_payload, "bios", default={}))
    os_payload = _safe_dict(_safe_get_nested(system_info_payload, "os", default={}))

    return {
        "cpu": {
            "name": _safe_text(cpu_payload.get("name")),
            "physical_cores": cpu_payload.get("physical_cores"),
            "logical_processors": cpu_payload.get("logical_processors")
            or cpu_payload.get("logical_cores"),
            "threads": cpu_payload.get("threads")
            or cpu_payload.get("logical_processors")
            or cpu_payload.get("logical_cores"),
            "max_clock_mhz": _round_optional_number(
                cpu_payload.get("max_clock_mhz") or cpu_payload.get("max_frequency_mhz")
            ),
        },
        "gpu": {
            "name": _safe_text(gpu_payload.get("name")),
            "driver_version": _safe_text(gpu_payload.get("driver_version")),
            "adapter_ram_gb": _round_optional_number(gpu_payload.get("adapter_ram_gb")),
        },
        "ram": {
            "total_gb": _round_optional_number(ram_payload.get("total_gb")),
            "modules_count": ram_payload.get("modules_count"),
            "modules": _safe_list(ram_payload.get("modules") or ram_payload.get("memory_modules")),
        },
        "motherboard": {
            "manufacturer": _safe_text(motherboard_payload.get("manufacturer")),
            "model": _safe_text(
                motherboard_payload.get("model") or motherboard_payload.get("product")
            ),
            "product": _safe_text(motherboard_payload.get("product")),
        },
        "bios": {
            "manufacturer": _safe_text(
                bios_payload.get("manufacturer")
                or motherboard_payload.get("bios_manufacturer")
            ),
            "version": _safe_text(
                bios_payload.get("version") or motherboard_payload.get("bios_version")
            ),
            "release_date": _safe_text(
                bios_payload.get("release_date") or motherboard_payload.get("release_date")
            ),
        },
        "os": {
            "name": _safe_text(os_payload.get("name") or os_payload.get("caption")),
            "version": _safe_text(os_payload.get("version")),
            "architecture": _safe_text(os_payload.get("architecture")),
        },
        "drives_count": drives_count,
    }


def _build_dashboard_device_payload(
    device: Device | None,
    configuration_payload: object = None,
) -> dict[str, object]:
    configuration = (
        configuration_payload.copy()
        if isinstance(configuration_payload, dict)
        else {}
    )
    ram_payload = (
        configuration.get("ram")
        if isinstance(configuration.get("ram"), dict)
        else {}
    )
    motherboard_payload = (
        configuration.get("motherboard")
        if isinstance(configuration.get("motherboard"), dict)
        else None
    )
    bios_payload = (
        configuration.get("bios")
        if isinstance(configuration.get("bios"), dict)
        else None
    )
    os_payload = (
        configuration.get("os")
        if isinstance(configuration.get("os"), dict)
        else None
    )

    if device is None:
        return {
            "id": None,
            "name": None,
            "cpu": None,
            "gpu": None,
            "ram_total_gb": ram_payload.get("total_gb"),
            "ram_modules_count": ram_payload.get("modules_count"),
            "motherboard": motherboard_payload,
            "bios": bios_payload,
            "os": os_payload,
        }
    return {
        "id": device.id,
        "name": device.name,
        "cpu": device.cpu,
        "gpu": device.gpu,
        "ram_total_gb": ram_payload.get("total_gb"),
        "ram_modules_count": ram_payload.get("modules_count"),
        "motherboard": motherboard_payload,
        "bios": bios_payload,
        "os": os_payload,
    }


def _merge_ml_prediction_into_status_payloads(
    warnings_payload: object,
    recommendations_payload: object,
    ml_prediction_payload: object,
) -> tuple[dict[str, object], dict[str, object]]:
    warnings_result = warnings_payload.copy() if isinstance(warnings_payload, dict) else {}
    recommendations_result = (
        recommendations_payload.copy()
        if isinstance(recommendations_payload, dict)
        else {}
    )

    if not isinstance(ml_prediction_payload, dict):
        return warnings_result, recommendations_result
    if ml_prediction_payload.get("available") is not True:
        return warnings_result, recommendations_result

    prediction_payload = ml_prediction_payload.get("prediction")
    if not isinstance(prediction_payload, dict):
        return warnings_result, recommendations_result
    if prediction_payload.get("prediction") != 1:
        return warnings_result, recommendations_result

    ml_warning_message = (
        "ML-\u043c\u043e\u0434\u0435\u043b\u044c \u0432\u044b\u044f\u0432\u0438\u043b\u0430 "
        "\u043f\u043e\u0432\u044b\u0448\u0435\u043d\u043d\u044b\u0439 \u0440\u0438\u0441\u043a "
        "\u043f\u043e SMART-\u043f\u0440\u0438\u0437\u043d\u0430\u043a\u0430\u043c "
        "\u043d\u0430\u043a\u043e\u043f\u0438\u0442\u0435\u043b\u044f."
    )
    risk_percent = prediction_payload.get("risk_percent")
    warning_item = {
        "level": "warning",
        "component": "Disk",
        "metric": "ml_smart_failure_prediction",
        "value": risk_percent,
        "unit": "%",
        "message": ml_warning_message,
    }

    warning_items = warnings_result.get("items")
    if not isinstance(warning_items, list):
        warning_items = []
    if not any(
        isinstance(item, dict) and item.get("metric") == "ml_smart_failure_prediction"
        for item in warning_items
    ):
        warning_items.append(warning_item)
    warnings_result["items"] = warning_items
    warnings_result["available"] = True

    components = warnings_result.get("components")
    if not isinstance(components, dict):
        components = _unknown_component_status()
    components["Disk"] = "critical"
    warnings_result["components"] = components

    current_status = warnings_result.get("status")
    if current_status != "critical":
        warnings_result["status"] = "critical"

    current_health_score = warnings_result.get("health_score")
    if isinstance(current_health_score, (int, float)):
        warnings_result["health_score"] = min(current_health_score, 60)
    else:
        warnings_result["health_score"] = 60

    recommendation_items = recommendations_result.get("items")
    if not isinstance(recommendation_items, list):
        recommendation_items = []

    ml_recommendation_message = (
        "\u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0443\u0435\u0442\u0441\u044f "
        "\u0441\u043e\u0437\u0434\u0430\u0442\u044c \u0438\u043b\u0438 "
        "\u043e\u0431\u043d\u043e\u0432\u0438\u0442\u044c \u0440\u0435\u0437\u0435\u0440\u0432\u043d\u0443\u044e "
        "\u043a\u043e\u043f\u0438\u044e \u0432\u0430\u0436\u043d\u044b\u0445 \u0434\u0430\u043d\u043d\u044b\u0445, "
        "\u043f\u0440\u043e\u0432\u0435\u0441\u0442\u0438 \u0440\u0430\u0441\u0448\u0438\u0440\u0435\u043d\u043d\u0443\u044e "
        "SMART-\u0434\u0438\u0430\u0433\u043d\u043e\u0441\u0442\u0438\u043a\u0443 \u0438 "
        "\u043d\u0430\u0431\u043b\u044e\u0434\u0430\u0442\u044c \u0437\u0430 \u0434\u0438\u043d\u0430\u043c\u0438\u043a\u043e\u0439 "
        "\u043f\u043e\u043a\u0430\u0437\u0430\u0442\u0435\u043b\u0435\u0439."
    )
    if ml_recommendation_message.strip():
        if not any(
            isinstance(item, dict) and item.get("message") == ml_recommendation_message
            for item in recommendation_items
        ):
            recommendation_items.append(
                {
                    "priority": "high",
                    "component": "Disk",
                    "metric": "ml_smart_failure_prediction",
                    "message": ml_recommendation_message,
                    "reason": ml_warning_message,
                }
            )

    recommendations_result["items"] = recommendation_items
    recommendations_result["available"] = True
    return warnings_result, recommendations_result


def _has_any_sensor_data(sensor_payload: object) -> bool:
    if not isinstance(sensor_payload, dict):
        return False

    for field_name in (
        "temperatures",
        "fans",
        "voltages",
        "powers",
        "clocks",
        "loads",
        "controls",
        "data",
    ):
        field_value = sensor_payload.get(field_name)
        if isinstance(field_value, list) and field_value:
            return True
    return False


def _check_database_health() -> dict[str, object]:
    database_payload = {
        "type": DATABASE_TYPE,
        "url_configured": DATABASE_URL_CONFIGURED,
    }
    if DATABASE_TYPE == "sqlite":
        database_payload["database_file"] = DATABASE_FILE

    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {
            "status": "ok",
            **database_payload,
        }
    except Exception as error:
        return {
            "status": "error",
            **database_payload,
            "error": _safe_error_text(error),
        }


def _check_ml_model_health() -> dict[str, object]:
    try:
        artifact = load_smart_model_artifact()
        return {
            "status": "ok",
            "model_name": artifact.get("model_name") or artifact.get("balanced_model_name"),
            "prediction_mode": artifact.get("prediction_mode", "balanced"),
            "target_column": artifact.get("target_column"),
            "threshold": artifact.get("best_threshold"),
        }
    except Exception as error:
        return {
            "status": "error",
            "error": _safe_error_text(error),
        }


def _check_sensors_health() -> dict[str, object]:
    try:
        sensor_payload = collect_hardware_sensors()
        sources = sensor_payload.get("sources") if isinstance(sensor_payload, dict) else None
        has_sources = isinstance(sources, dict) and any(bool(value) for value in sources.values())
        has_sensor_data = _has_any_sensor_data(sensor_payload)
        return {
            "status": "ok" if has_sources or has_sensor_data else "partial",
            "sources": sources if isinstance(sources, dict) else None,
        }
    except Exception as error:
        return {
            "status": "error",
            "error": _safe_error_text(error),
        }


def _check_smart_health() -> dict[str, object]:
    try:
        smart_payload = collect_smart_data()
        drives = smart_payload.get("drives") if isinstance(smart_payload, dict) else None
        sources = smart_payload.get("sources") if isinstance(smart_payload, dict) else None
        drives_count = len(drives) if isinstance(drives, list) else 0
        return {
            "status": "ok" if drives_count > 0 else "partial",
            "drives_count": drives_count,
            "sources": sources,
        }
    except Exception as error:
        return {
            "status": "error",
            "error": _safe_error_text(error),
        }


def _build_health_check_payload() -> dict[str, object]:
    external_tools_payload = _build_external_tools_payload()
    checks = {
        "backend": {"status": "ok"},
        "database": _check_database_health(),
        "ml_model": _check_ml_model_health(),
        "sensors": _check_sensors_health(),
        "smart": _check_smart_health(),
        "external_tools": external_tools_payload,
        "libre_hardware_monitor": _safe_dict(
            external_tools_payload.get("libre_hardware_monitor")
        ),
    }

    database_status = checks["database"].get("status")
    ml_model_status = checks["ml_model"].get("status")
    sensors_status = checks["sensors"].get("status")
    smart_status = checks["smart"].get("status")

    overall_status = "ok"
    if database_status == "error" or ml_model_status == "error":
        overall_status = "error"
    elif sensors_status in {"partial", "error"} or smart_status in {"partial", "error"}:
        overall_status = "partial"

    return {
        "status": overall_status,
        "checks": checks,
    }


async def background_metrics_collector() -> None:
    while True:
        with SessionLocal() as db:
            device = get_default_device(db)
            if device is None:
                print("Device for metrics collection not found")
            else:
                metrics = await asyncio.to_thread(collect_current_metrics)
                sensor_payload = await asyncio.to_thread(collect_hardware_sensors)
                key_metrics = extract_key_metrics(sensor_payload)
                measurement = Measurement(
                    device_id=device.id,
                    cpu_usage=metrics["cpu_usage"],
                    gpu_usage=metrics["gpu_usage"],
                    ram_usage=metrics["ram_usage"],
                    disk_usage=metrics["disk_usage"],
                    cpu_temperature=key_metrics.get("cpu_temperature"),
                    gpu_temperature=key_metrics.get("gpu_temperature"),
                    ram_temperature=key_metrics.get("ram_temperature"),
                    disk_temperature=key_metrics.get("disk_temperature"),
                    cpu_power=key_metrics.get("cpu_power"),
                    gpu_power=key_metrics.get("gpu_power"),
                    system_fan_rpm=key_metrics.get("system_fan_rpm"),
                    disk_life=key_metrics.get("disk_life"),
                    disk_power_on_hours=key_metrics.get("disk_power_on_hours"),
                    recorded_at=datetime.utcnow(),
                )
                db.add(measurement)
                db.commit()

        await asyncio.sleep(settings.METRICS_COLLECTION_INTERVAL_SECONDS)


@app.on_event("startup")
async def startup() -> None:
    global EXTERNAL_TOOLS_STATUS

    try:
        EXTERNAL_TOOLS_STATUS["libre_hardware_monitor"] = await asyncio.to_thread(
            start_lhm_if_needed
        )
        Base.metadata.create_all(bind=engine)
        await asyncio.to_thread(ensure_default_device_exists)
        with engine.begin() as connection:
            inspector = inspect(connection)
            measurement_columns = {
                column["name"] for column in inspector.get_columns("measurements")
            }
            for column_name, column_type in MEASUREMENT_COLUMN_TYPES.items():
                if column_name in measurement_columns:
                    continue
                connection.execute(
                    text(
                        f"ALTER TABLE measurements ADD COLUMN {column_name} {column_type}"
                    )
                )
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            get_default_device(db)
        asyncio.create_task(background_metrics_collector())
        print("Database connected")
    except Exception as error:
        print(error)


@app.get("/health")
def health() -> dict[str, object]:
    return _build_health_check_payload()


@app.get("/metrics/current")
def get_current_metrics() -> dict[str, float | None]:
    return collect_current_metrics()


@app.get("/system/info")
def get_system_info() -> dict[str, object]:
    return collect_system_info()


@app.get("/system/sensors")
def get_system_sensors() -> dict[str, object]:
    return collect_hardware_sensors()


@app.get("/system/smart")
def get_system_smart() -> dict[str, object]:
    return collect_smart_data()


@app.get("/system/status")
def get_system_status() -> dict[str, object]:
    metrics_data: dict[str, object] | None = None
    sensors_data: dict[str, object] | None = None

    try:
        metrics_data = collect_current_metrics()
        metrics_payload: dict[str, object] = {
            "available": True,
            "data": metrics_data,
        }
    except Exception as error:
        metrics_payload = {
            "available": False,
            "error": _safe_error_text(error),
        }

    try:
        sensors_data = collect_hardware_sensors()
        sensors_payload = _build_compact_sensors_payload(sensors_data)
    except Exception as error:
        sensors_payload = {
            "available": False,
            "error": _safe_error_text(error),
        }

    try:
        smart_data = collect_smart_data()
        smart_payload = _build_compact_smart_payload(smart_data)
    except Exception as error:
        smart_payload = {
            "available": False,
            "error": _safe_error_text(error),
        }

    analysis_payload = _build_system_status_analysis(
        metrics_data,
        sensors_data,
    )
    if (
        not isinstance(analysis_payload, tuple)
        or len(analysis_payload) != 2
        or not all(isinstance(item, dict) for item in analysis_payload)
    ):
        warnings_payload = {
            "available": False,
            "status": "unknown",
            "health_score": None,
            "components": _unknown_component_status(),
            "items": [],
            "error": "System status analysis returned an unexpected result.",
        }
        recommendations_payload = {
            "available": False,
            "items": [],
            "error": "System status analysis returned an unexpected result.",
        }
    else:
        warnings_payload, recommendations_payload = analysis_payload

    try:
        ml_prediction_result = predict_current_smart_failure()
        ml_prediction_payload = {
            "available": True,
            "prediction": ml_prediction_result.get("prediction"),
            "source_drive": ml_prediction_result.get("source_drive_summary"),
            "predict_payload": ml_prediction_result.get("predict_payload"),
            "normalized_features": ml_prediction_result.get("normalized_features"),
        }
    except Exception as error:
        ml_prediction_payload = {
            "available": False,
            "error": _safe_error_text(error),
        }

    warnings_payload, recommendations_payload = _merge_ml_prediction_into_status_payloads(
        warnings_payload,
        recommendations_payload,
        ml_prediction_payload,
    )

    return {
        "metrics": metrics_payload,
        "sensors": sensors_payload,
        "smart": smart_payload,
        "external_tools": _build_external_tools_payload(),
        "warnings": warnings_payload,
        "recommendations": recommendations_payload,
        "ml_prediction": ml_prediction_payload,
    }


@app.get("/dashboard")
def get_dashboard() -> dict[str, object]:
    try:
        with SessionLocal() as db:
            default_device = get_default_device(db)
        return _build_dashboard_payload(
            get_system_status(),
            default_device,
            _collect_system_info_safe(),
        )
    except Exception:
        return _build_dashboard_payload({}, None, {})


@app.get("/dashboard/history")
def get_dashboard_history(
    limit: int = Query(default=120, ge=1, le=1000),
    device_id: int | None = Query(default=None),
) -> dict[str, object]:
    with SessionLocal() as db:
        resolved_device = (
            db.query(Device).filter(Device.id == device_id).first()
            if device_id is not None
            else get_default_device(db)
        )
        ordered_measurements = (
            _get_dashboard_measurements(db, resolved_device.id, limit)
            if resolved_device is not None
            else []
        )
    items = [
        _measurement_to_dashboard_history_item(measurement)
        for measurement in ordered_measurements
    ]

    return {
        "device_id": resolved_device.id if resolved_device is not None else None,
        "limit": limit,
        "count": len(items),
        "items": items,
        "series": {
            "usage": ["cpu_usage", "gpu_usage", "ram_usage", "disk_usage"],
            "temperatures": [
                "cpu_temperature",
                "gpu_temperature",
                "ram_temperature",
                "disk_temperature",
            ],
            "power": ["cpu_power", "gpu_power"],
            "cooling": ["system_fan_rpm"],
            "disk": ["disk_life", "disk_power_on_hours"],
        },
    }


@app.get("/dashboard/charts")
def get_dashboard_charts(
    limit: int = Query(default=120, ge=1, le=1000),
    device_id: int | None = Query(default=None),
) -> dict[str, object]:
    with SessionLocal() as db:
        resolved_device = (
            db.query(Device).filter(Device.id == device_id).first()
            if device_id is not None
            else get_default_device(db)
        )
        measurements = (
            _get_dashboard_measurements(db, resolved_device.id, limit)
            if resolved_device is not None
            else []
        )
    return _build_dashboard_charts_payload(
        measurements,
        resolved_device.id if resolved_device is not None else None,
        limit,
    )


@app.post("/ml/smart/predict")
def predict_ml_smart(request: SmartPredictionRequest) -> dict[str, object]:
    return predict_smart_failure(request.model_dump())


@app.get("/ml/smart/model/info")
def get_ml_smart_model_info() -> dict[str, object]:
    try:
        return get_smart_model_info()
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.get("/ml/smart/predict/current")
def predict_ml_smart_current() -> dict[str, object]:
    try:
        return predict_current_smart_failure()
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/devices")
def create_device(
    name: str = Body(...),
    cpu: str = Body(...),
    gpu: str = Body(...),
) -> dict[str, object]:
    with SessionLocal() as db:
        device = Device(
            name=name,
            cpu=cpu,
            gpu=gpu,
            created_at=datetime.utcnow(),
        )
        db.add(device)
        db.commit()
        db.refresh(device)
        return {
            "id": device.id,
            "name": device.name,
            "cpu": device.cpu,
            "gpu": device.gpu,
            "created_at": device.created_at,
        }


@app.get("/devices")
def get_devices() -> list[dict[str, object]]:
    with SessionLocal() as db:
        devices = db.query(Device).all()
        return [
            {
                "id": device.id,
                "name": device.name,
                "cpu": device.cpu,
                "gpu": device.gpu,
                "created_at": device.created_at,
            }
            for device in devices
        ]


@app.get("/devices/{id}")
def get_device(id: int) -> dict[str, object]:
    with SessionLocal() as db:
        device = db.query(Device).filter(Device.id == id).first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")
        return {
            "id": device.id,
            "name": device.name,
            "cpu": device.cpu,
            "gpu": device.gpu,
            "created_at": device.created_at,
        }


@app.post("/devices/{id}/measurements")
def create_measurement(
    id: int,
    cpu_usage: float = Body(...),
    gpu_usage: float | None = Body(default=None),
    ram_usage: float = Body(...),
    disk_usage: float = Body(...),
    cpu_temperature: float | None = Body(default=None),
    gpu_temperature: float | None = Body(default=None),
    ram_temperature: float | None = Body(default=None),
    disk_temperature: float | None = Body(default=None),
    cpu_power: float | None = Body(default=None),
    gpu_power: float | None = Body(default=None),
    system_fan_rpm: float | None = Body(default=None),
    disk_life: float | None = Body(default=None),
    disk_power_on_hours: int | None = Body(default=None),
) -> dict[str, object]:
    with SessionLocal() as db:
        device = db.query(Device).filter(Device.id == id).first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")

        measurement = Measurement(
            device_id=id,
            cpu_usage=cpu_usage,
            gpu_usage=gpu_usage,
            ram_usage=ram_usage,
            disk_usage=disk_usage,
            cpu_temperature=cpu_temperature,
            gpu_temperature=gpu_temperature,
            ram_temperature=ram_temperature,
            disk_temperature=disk_temperature,
            cpu_power=cpu_power,
            gpu_power=gpu_power,
            system_fan_rpm=system_fan_rpm,
            disk_life=disk_life,
            disk_power_on_hours=disk_power_on_hours,
            recorded_at=datetime.utcnow(),
        )
        db.add(measurement)
        db.commit()
        db.refresh(measurement)
        return measurement_to_dict(measurement)


@app.post("/devices/{id}/measurements/collect")
def collect_measurement(id: int) -> dict[str, object]:
    with SessionLocal() as db:
        device = db.query(Device).filter(Device.id == id).first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")

        metrics = collect_current_metrics()
        sensor_payload = collect_hardware_sensors()
        key_metrics = extract_key_metrics(sensor_payload)
        measurement = Measurement(
            device_id=id,
            cpu_usage=metrics["cpu_usage"],
            gpu_usage=metrics["gpu_usage"],
            ram_usage=metrics["ram_usage"],
            disk_usage=metrics["disk_usage"],
            cpu_temperature=key_metrics.get("cpu_temperature"),
            gpu_temperature=key_metrics.get("gpu_temperature"),
            ram_temperature=key_metrics.get("ram_temperature"),
            disk_temperature=key_metrics.get("disk_temperature"),
            cpu_power=key_metrics.get("cpu_power"),
            gpu_power=key_metrics.get("gpu_power"),
            system_fan_rpm=key_metrics.get("system_fan_rpm"),
            disk_life=key_metrics.get("disk_life"),
            disk_power_on_hours=key_metrics.get("disk_power_on_hours"),
            recorded_at=datetime.utcnow(),
        )
        db.add(measurement)
        db.commit()
        db.refresh(measurement)
        return measurement_to_dict(measurement)


@app.get("/devices/{id}/measurements")
def get_measurements(id: int) -> list[dict[str, object]]:
    with SessionLocal() as db:
        device = db.query(Device).filter(Device.id == id).first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")

        measurements = (
            db.query(Measurement)
            .filter(Measurement.device_id == id)
            .order_by(Measurement.recorded_at.asc())
            .all()
        )
        return [measurement_to_dict(measurement) for measurement in measurements]


@app.get("/devices/{id}/measurements/latest")
def get_latest_measurement(id: int) -> dict[str, object]:
    with SessionLocal() as db:
        device = db.query(Device).filter(Device.id == id).first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")

        measurement = (
            db.query(Measurement)
            .filter(Measurement.device_id == id)
            .order_by(Measurement.recorded_at.desc())
            .first()
        )
        if measurement is None:
            raise HTTPException(status_code=404, detail="Measurements not found")

        return measurement_to_dict(measurement)


@app.get("/devices/{id}/measurements/stats")
def get_measurements_stats(id: int) -> dict[str, object]:
    with SessionLocal() as db:
        device = db.query(Device).filter(Device.id == id).first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")

        measurements = db.query(Measurement).filter(Measurement.device_id == id).all()
        if not measurements:
            raise HTTPException(status_code=404, detail="Measurements not found")

        cpu_values = [measurement.cpu_usage for measurement in measurements]
        gpu_values = [
            measurement.gpu_usage
            for measurement in measurements
            if measurement.gpu_usage is not None
        ]
        ram_values = [measurement.ram_usage for measurement in measurements]
        disk_values = [measurement.disk_usage for measurement in measurements]

        return {
            "device_id": id,
            "cpu": {
                "avg": sum(cpu_values) / len(cpu_values),
                "max": max(cpu_values),
                "min": min(cpu_values),
            },
            "gpu": {
                "avg": sum(gpu_values) / len(gpu_values) if gpu_values else None,
                "max": max(gpu_values) if gpu_values else None,
                "min": min(gpu_values) if gpu_values else None,
            },
            "ram": {
                "avg": sum(ram_values) / len(ram_values),
                "max": max(ram_values),
                "min": min(ram_values),
            },
            "disk": {
                "avg": sum(disk_values) / len(disk_values),
                "max": max(disk_values),
                "min": min(disk_values),
            },
        }


@app.get("/devices/{id}/measurements/history")
def get_measurements_history(id: int) -> list[dict[str, object]]:
    with SessionLocal() as db:
        device = db.query(Device).filter(Device.id == id).first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")

        measurements = (
            db.query(Measurement)
            .filter(Measurement.device_id == id)
            .order_by(Measurement.recorded_at.desc())
            .limit(50)
            .all()
        )

        return [
            measurement_to_dict(measurement, include_device_id=False)
            for measurement in measurements
        ]


@app.get("/devices/{id}/warnings")
def get_device_warnings(id: int) -> dict[str, object]:
    with SessionLocal() as db:
        device = db.query(Device).filter(Device.id == id).first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")

        measurement = (
            db.query(Measurement)
            .filter(Measurement.device_id == id)
            .order_by(Measurement.recorded_at.desc())
            .first()
        )
        if measurement is None:
            raise HTTPException(status_code=404, detail="Measurements not found")

        warning_analysis = analyze_measurement(measurement)

        return {
            "device_id": id,
            "status": warning_analysis["status"],
            "health_score": warning_analysis["health_score"],
            "warnings": warning_analysis["warnings"],
            "latest_measurement": measurement_to_dict(
                measurement,
                include_device_id=False,
            ),
        }


@app.get("/devices/{id}/health")
def get_device_health(id: int) -> dict[str, object]:
    with SessionLocal() as db:
        device = db.query(Device).filter(Device.id == id).first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")

        measurement = (
            db.query(Measurement)
            .filter(Measurement.device_id == id)
            .order_by(Measurement.recorded_at.desc())
            .first()
        )
        if measurement is None:
            raise HTTPException(status_code=404, detail="Measurements not found")

        analysis = analyze_measurement(measurement)
        component_status = build_component_status(analysis["warnings"])
        critical_count = sum(
            1 for warning in analysis["warnings"] if warning["level"] == "critical"
        )
        warning_count = sum(
            1 for warning in analysis["warnings"] if warning["level"] == "warning"
        )

        return {
            "device_id": id,
            "overall_status": analysis["status"],
            "health_score": analysis["health_score"],
            "components": component_status,
            "warnings_count": len(analysis["warnings"]),
            "critical_count": critical_count,
            "warning_count": warning_count,
            "latest_measurement": measurement_to_dict(measurement),
        }


@app.get("/devices/{id}/recommendations")
def get_device_recommendations(id: int) -> dict[str, object]:
    with SessionLocal() as db:
        device = db.query(Device).filter(Device.id == id).first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")

        measurement = (
            db.query(Measurement)
            .filter(Measurement.device_id == id)
            .order_by(Measurement.recorded_at.desc())
            .first()
        )
        if measurement is None:
            raise HTTPException(status_code=404, detail="Measurements not found")

        analysis = analyze_measurement(measurement)
        recommendations = build_recommendations(analysis["warnings"])

        return {
            "device_id": id,
            "status": analysis["status"],
            "health_score": analysis["health_score"],
            "recommendations_count": len(recommendations),
            "recommendations": recommendations,
            "warnings": analysis["warnings"],
            "latest_measurement": measurement_to_dict(measurement),
        }


@app.get("/devices/{id}/components")
def get_device_components(id: int) -> dict[str, object]:
    with SessionLocal() as db:
        device = db.query(Device).filter(Device.id == id).first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")

        measurement = (
            db.query(Measurement)
            .filter(Measurement.device_id == id)
            .order_by(Measurement.recorded_at.desc())
            .first()
        )
        if measurement is None:
            raise HTTPException(status_code=404, detail="Measurements not found")

        analysis = analyze_measurement(measurement)
        component_status = build_component_status(analysis["warnings"])
        recommendations = build_recommendations(analysis["warnings"])

        warnings_by_component = {
            "CPU": [],
            "GPU": [],
            "RAM": [],
            "Disk": [],
            "Cooling": [],
        }
        for warning in analysis["warnings"]:
            component = warning.get("component")
            if component in warnings_by_component:
                warnings_by_component[component].append(warning)

        recommendations_by_component = {
            "CPU": [],
            "GPU": [],
            "RAM": [],
            "Disk": [],
            "Cooling": [],
        }
        for recommendation in recommendations:
            component = recommendation.get("component")
            if component in recommendations_by_component:
                recommendations_by_component[component].append(recommendation)

        components = {
            "CPU": {
                "status": component_status["CPU"],
                "metrics": {
                    "usage": measurement.cpu_usage,
                    "temperature": measurement.cpu_temperature,
                    "power": measurement.cpu_power,
                },
                "warnings": warnings_by_component["CPU"],
                "recommendations": recommendations_by_component["CPU"],
            },
            "GPU": {
                "status": component_status["GPU"],
                "metrics": {
                    "usage": measurement.gpu_usage,
                    "temperature": measurement.gpu_temperature,
                    "power": measurement.gpu_power,
                },
                "warnings": warnings_by_component["GPU"],
                "recommendations": recommendations_by_component["GPU"],
            },
            "RAM": {
                "status": component_status["RAM"],
                "metrics": {
                    "usage": measurement.ram_usage,
                    "temperature": measurement.ram_temperature,
                },
                "warnings": warnings_by_component["RAM"],
                "recommendations": recommendations_by_component["RAM"],
            },
            "Disk": {
                "status": component_status["Disk"],
                "metrics": {
                    "usage": measurement.disk_usage,
                    "temperature": measurement.disk_temperature,
                    "life": measurement.disk_life,
                    "power_on_hours": measurement.disk_power_on_hours,
                },
                "warnings": warnings_by_component["Disk"],
                "recommendations": recommendations_by_component["Disk"],
            },
            "Cooling": {
                "status": component_status["Cooling"],
                "metrics": {
                    "system_fan_rpm": measurement.system_fan_rpm,
                },
                "warnings": warnings_by_component["Cooling"],
                "recommendations": recommendations_by_component["Cooling"],
            },
        }

        return {
            "device_id": id,
            "overall_status": analysis["status"],
            "health_score": analysis["health_score"],
            "components": components,
            "latest_measurement": measurement_to_dict(measurement),
        }


@app.put("/devices/{id}")
def update_device(
    id: int,
    name: str = Body(...),
    cpu: str = Body(...),
    gpu: str = Body(...),
) -> dict[str, object]:
    with SessionLocal() as db:
        device = db.query(Device).filter(Device.id == id).first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")
        device.name = name
        device.cpu = cpu
        device.gpu = gpu
        db.commit()
        db.refresh(device)
        return {
            "id": device.id,
            "name": device.name,
            "cpu": device.cpu,
            "gpu": device.gpu,
            "created_at": device.created_at,
        }


@app.delete("/devices/{id}")
def delete_device(id: int) -> dict[str, str]:
    with SessionLocal() as db:
        device = db.query(Device).filter(Device.id == id).first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")
        db.delete(device)
        db.commit()
        return {"message": "Device deleted successfully"}
