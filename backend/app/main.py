from datetime import datetime

from fastapi import Body, FastAPI
from sqlalchemy import text

from app.core.database import Base, SessionLocal, engine
from app.core.config import settings
from app.models.device import Device

app = FastAPI(title=settings.APP_NAME)


@app.on_event("startup")
def startup() -> None:
    try:
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        print("Database connected")
    except Exception as error:
        print(error)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
