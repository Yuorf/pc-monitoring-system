import asyncio
from datetime import datetime

from fastapi import Body, FastAPI, HTTPException
from sqlalchemy import text

from app.core.database import Base, SessionLocal, engine
from app.core.config import settings
from app.models.device import Device
from app.models.measurement import Measurement
from app.services.system_metrics import collect_current_metrics
from app.services.warning_service import analyze_measurement

app = FastAPI(title=settings.APP_NAME)


async def background_metrics_collector() -> None:
    while True:
        with SessionLocal() as db:
            device = db.query(Device).filter(Device.id == 1).first()
            if device is None:
                print("Device for metrics collection not found")
            else:
                metrics = await asyncio.to_thread(collect_current_metrics)
                measurement = Measurement(
                    device_id=device.id,
                    cpu_usage=metrics["cpu_usage"],
                    ram_usage=metrics["ram_usage"],
                    disk_usage=metrics["disk_usage"],
                    recorded_at=datetime.utcnow(),
                )
                db.add(measurement)
                db.commit()

        await asyncio.sleep(settings.METRICS_COLLECTION_INTERVAL_SECONDS)


@app.on_event("startup")
async def startup() -> None:
    try:
        Base.metadata.create_all(bind=engine)
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
def get_current_metrics() -> dict[str, float]:
    return collect_current_metrics()


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
    ram_usage: float = Body(...),
    disk_usage: float = Body(...),
) -> dict[str, object]:
    with SessionLocal() as db:
        device = db.query(Device).filter(Device.id == id).first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")

        measurement = Measurement(
            device_id=id,
            cpu_usage=cpu_usage,
            ram_usage=ram_usage,
            disk_usage=disk_usage,
            recorded_at=datetime.utcnow(),
        )
        db.add(measurement)
        db.commit()
        db.refresh(measurement)
        return {
            "id": measurement.id,
            "device_id": measurement.device_id,
            "cpu_usage": measurement.cpu_usage,
            "ram_usage": measurement.ram_usage,
            "disk_usage": measurement.disk_usage,
            "recorded_at": measurement.recorded_at,
        }


@app.post("/devices/{id}/measurements/collect")
def collect_measurement(id: int) -> dict[str, object]:
    with SessionLocal() as db:
        device = db.query(Device).filter(Device.id == id).first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")

        metrics = collect_current_metrics()
        measurement = Measurement(
            device_id=id,
            cpu_usage=metrics["cpu_usage"],
            ram_usage=metrics["ram_usage"],
            disk_usage=metrics["disk_usage"],
            recorded_at=datetime.utcnow(),
        )
        db.add(measurement)
        db.commit()
        db.refresh(measurement)
        return {
            "id": measurement.id,
            "device_id": measurement.device_id,
            "cpu_usage": measurement.cpu_usage,
            "ram_usage": measurement.ram_usage,
            "disk_usage": measurement.disk_usage,
            "recorded_at": measurement.recorded_at,
        }


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
        return [
            {
                "id": measurement.id,
                "device_id": measurement.device_id,
                "cpu_usage": measurement.cpu_usage,
                "ram_usage": measurement.ram_usage,
                "disk_usage": measurement.disk_usage,
                "recorded_at": measurement.recorded_at,
            }
            for measurement in measurements
        ]


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

        return {
            "id": measurement.id,
            "device_id": measurement.device_id,
            "cpu_usage": measurement.cpu_usage,
            "ram_usage": measurement.ram_usage,
            "disk_usage": measurement.disk_usage,
            "recorded_at": measurement.recorded_at,
        }


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
            "warnings": warning_analysis["warnings"],
            "latest_measurement": {
                "id": measurement.id,
                "cpu_usage": measurement.cpu_usage,
                "ram_usage": measurement.ram_usage,
                "disk_usage": measurement.disk_usage,
                "recorded_at": measurement.recorded_at,
            },
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
