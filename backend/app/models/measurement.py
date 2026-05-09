from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer
from sqlalchemy.orm import synonym

from app.core.database import Base


class Measurement(Base):
    __tablename__ = "measurements"

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
    timestamp = Column("recorded_at", DateTime, default=datetime.utcnow, nullable=False)
    recorded_at = synonym("timestamp")

    cpu_temperature = Column(Float, nullable=True)
    gpu_temperature = Column(Float, nullable=True)
    ram_temperature = Column(Float, nullable=True)
    disk_temperature = Column(Float, nullable=True)
    cpu_power = Column(Float, nullable=True)
    gpu_power = Column(Float, nullable=True)
    system_fan_rpm = Column(Float, nullable=True)
    disk_life = Column(Float, nullable=True)
    disk_power_on_hours = Column(Integer, nullable=True)

    cpu_usage = Column(Float, nullable=True)
    gpu_usage = Column(Float, nullable=True)
    ram_usage = Column(Float, nullable=True)
    disk_usage = Column(Float, nullable=True)
