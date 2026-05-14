import asyncio
from datetime import datetime

from fastapi import Body, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import inspect, text

from app.core.database import Base, SessionLocal, engine
from app.core.config import settings
from app.models.device import Device
from app.models.measurement import Measurement
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


def _safe_error_text(error: Exception) -> str:
    error_text = str(error).strip()
    return error_text or error.__class__.__name__


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
        "\u043e\u0442\u043a\u0430\u0437\u0430 \u043d\u0430\u043a\u043e\u043f\u0438\u0442\u0435\u043b\u044f "
        "\u0432 \u0442\u0435\u0447\u0435\u043d\u0438\u0435 30 \u0434\u043d\u0435\u0439."
    )
    risk_percent = prediction_payload.get("risk_percent")
    warning_item = {
        "level": "critical",
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

    ml_recommendation_message = prediction_payload.get("recommendation")
    if isinstance(ml_recommendation_message, str) and ml_recommendation_message.strip():
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
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as error:
        return {
            "status": "error",
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
    checks = {
        "backend": {"status": "ok"},
        "database": _check_database_health(),
        "ml_model": _check_ml_model_health(),
        "sensors": _check_sensors_health(),
        "smart": _check_smart_health(),
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
            device = db.query(Device).filter(Device.id == 1).first()
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
    try:
        Base.metadata.create_all(bind=engine)
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
            db.query(Device).filter(Device.id == 1).first()
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
        sensors_payload = {
            "available": True,
            **sensors_data,
        }
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
        "warnings": warnings_payload,
        "recommendations": recommendations_payload,
        "ml_prediction": ml_prediction_payload,
    }


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
