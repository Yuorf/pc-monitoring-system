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
from app.services.ml_prediction_service import predict_smart_failure
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
def health() -> dict[str, str]:
    return {"status": "ok"}


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


@app.post("/ml/smart/predict")
def predict_ml_smart(request: SmartPredictionRequest) -> dict[str, object]:
    return predict_smart_failure(request.model_dump())


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
